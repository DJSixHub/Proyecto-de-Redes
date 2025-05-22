# core/messaging.py

import threading
import socket
import os
from datetime import datetime

from core.protocol import (
    UDP_PORT,
    BROADCAST_UID,
    pack_header,
    unpack_header,
    pack_response,
    unpack_response,
    HEADER_SIZE,
    RESPONSE_SIZE
)


class Messaging:
    """
    Envía y recibe mensajes y archivos siguiendo el protocolo,
    con manejo de excepciones para evitar que un timeout o error
    de red haga crashear la aplicación.
    """

    def __init__(self, user_id: bytes, discovery, history_store):
        self.user_id = user_id
        self.discovery = discovery
        self.history_store = history_store
        self.sock = discovery.sock

    def _handshake_send(self, header: bytes, body: bytes, dest: tuple):
        """
        Realiza el handshake completo en un socket efímero:
          1) enviar header → esperar ACK
          2) enviar body   → esperar ACK
        Captura socket.timeout y OSError, y eleva RuntimeError con mensaje claro.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', 0))
        sock.settimeout(2.0)

        try:
            # 1) Header → ACK
            sock.sendto(header, dest)
            while True:
                data, _ = sock.recvfrom(4096)
                if len(data) >= RESPONSE_SIZE:
                    resp = unpack_response(data[:RESPONSE_SIZE])
                    if resp['status'] == 0:
                        break

            # 2) Body → ACK
            sock.sendto(body, dest)
            while True:
                data, _ = sock.recvfrom(4096)
                if len(data) >= RESPONSE_SIZE:
                    resp = unpack_response(data[:RESPONSE_SIZE])
                    if resp['status'] == 0:
                        break

        except socket.timeout:
            raise RuntimeError("No se recibió respuesta (timeout), el peer puede estar desconectado.")
        except OSError as e:
            raise RuntimeError(f"Error de red durante el handshake: {e}")
        finally:
            sock.close()

    def send(self, recipient: bytes, message: bytes):
        """
        Envía mensaje de texto (op_code=1). Atrapa errores situacionales
        y los convierte en RuntimeError para manejar en UI.
        """
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise RuntimeError("Peer no encontrado en discovery.")
        dest = (info['ip'], UDP_PORT)

        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=1,
            body_len=len(message)
        )

        try:
            self._handshake_send(header, message, dest)
        except RuntimeError as e:
            # No crash: propaga con mensaje claro
            raise

        # Registrar en historial sólo si todo fue exitoso
        self.history_store.append_message(
            sender=self.user_id.decode('utf-8'),
            recipient=recipient.decode('utf-8'),
            message=message.decode('utf-8'),
            timestamp=datetime.utcnow()
        )

    def send_file(self, recipient: bytes, file_path: str):
        """Envía archivo (op_code=2) con mismo manejo de errores."""
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise RuntimeError("Peer no encontrado en discovery.")
        dest = (info['ip'], UDP_PORT)

        filename = os.path.basename(file_path).encode('utf-8')
        with open(file_path, 'rb') as f:
            file_data = f.read()
        body = len(filename).to_bytes(2, 'big') + filename + file_data

        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=2,
            body_len=len(body)
        )

        try:
            self._handshake_send(header, body, dest)
        except RuntimeError:
            raise

        self.history_store.append_file(
            sender=self.user_id.decode('utf-8'),
            recipient=recipient.decode('utf-8'),
            filename=filename.decode('utf-8'),
            timestamp=datetime.utcnow()
        )

    def send_all(self, message: bytes):
        """Broadcast global; no handshake, pero manejamos posibles OSError."""
        try:
            header = pack_header(
                user_from=self.user_id,
                user_to=BROADCAST_UID,
                op_code=1,
                body_len=len(message)
            )
            self.sock.sendto(header + message, ('<broadcast>', UDP_PORT))
        except OSError as e:
            raise RuntimeError(f"Error al enviar broadcast global: {e}")

        # Registrar localmente
        for peer_id in self.discovery.get_peers().keys():
            self.history_store.append_message(
                sender=self.user_id.decode('utf-8'),
                recipient=peer_id.decode('utf-8'),
                message=message.decode('utf-8'),
                timestamp=datetime.utcnow()
            )

    # ... recv_loop y _handle_message_or_file se mantienen igual ...


    def _handle_message_or_file(self, hdr, initial_data: bytes, addr):
        """Procesa la recepción de body y registra mensajes/archivos entrantes."""
        peer_id = hdr['user_from']
        body_len = hdr['body_len']
        data = initial_data
        while len(data) < body_len:
            chunk, _ = self.sock.recvfrom(body_len - len(data))
            data += chunk

        # ACK body
        self.sock.sendto(pack_response(0, self.user_id), addr)

        if hdr['op_code'] == 1:
            text = data.decode('utf-8')
            self.history_store.append_message(
                sender=peer_id.decode('utf-8'),
                recipient=self.user_id.decode('utf-8'),
                message=text,
                timestamp=datetime.utcnow()
            )
        else:  # op_code 2: archivo
            name_len = int.from_bytes(data[:2], 'big')
            filename = data[2:2+name_len].decode('utf-8')
            file_data = data[2+name_len:]
            save_dir = 'received_files'
            os.makedirs(save_dir, exist_ok=True)
            with open(os.path.join(save_dir, filename), 'wb') as f:
                f.write(file_data)
            self.history_store.append_file(
                sender=peer_id.decode('utf-8'),
                recipient=self.user_id.decode('utf-8'),
                filename=filename,
                timestamp=datetime.utcnow()
            )

    def recv_loop(self):
        """
        Único bucle de recepción que despacha:
          - Echo-Reply (RESPONSE_FMT) → Discovery.handle_response
          - Echo-Request (HEADER_FMT op_code=0) → Discovery.handle_echo
          - Mensajes/archivos (op_code=1,2) → ACK header y _handle_message_or_file
        """
        while True:
            data, addr = self.sock.recvfrom(max(HEADER_SIZE, RESPONSE_SIZE, 4096))

            # Echo-Reply?
            if len(data) == RESPONSE_SIZE:
                self.discovery.handle_response(data, addr)
                continue

            if len(data) >= HEADER_SIZE:
                hdr = unpack_header(data[:HEADER_SIZE])

                # Echo-Request?
                if hdr['op_code'] == 0:
                    self.discovery.handle_echo(data, addr)
                    continue

                # Mensaje o archivo
                # ACK header
                self.sock.sendto(pack_response(0, self.user_id), addr)
                initial_body = data[HEADER_SIZE:]
                threading.Thread(
                    target=self._handle_message_or_file,
                    args=(hdr, initial_body, addr),
                    daemon=True
                ).start()
