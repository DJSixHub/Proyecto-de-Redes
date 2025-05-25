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
    Comunicación directa y envío múltiple con protocolo LCP.
    Cumple handshake: Header → ACK → Body → ACK.
    """

    def __init__(self, user_id: bytes, discovery, history_store):
        self.user_id = user_id
        self.discovery = discovery
        self.history_store = history_store
        # Reutilizamos el socket de discovery para enviar/recibir
        self.sock = discovery.sock

    def _wait_for_ack(self, expected_from: bytes, timeout: float = 2.0):
        """
        Espera un ACK válido, con timeout.  
        Filtra sólo datagramas de tamaño RESPONSE_SIZE y sólo status==0
        del peer esperado.
        """
        self.sock.settimeout(timeout)
        try:
            while True:
                data, _ = self.sock.recvfrom(4096)
                # 1) ignorar paquetes que no sean de tamaño ACK
                if len(data) != RESPONSE_SIZE:
                    continue
                # 2) intentar desempaquetar; si falla, ignorar
                try:
                    resp = unpack_response(data)
                except Exception:
                    continue
                # 3) sólo aceptar status==0 y responder correcto
                if resp['status'] == 0 and resp['responder'] == expected_from:
                    return
                # 4) si viene de otro, seguimos esperando
        except socket.timeout:
            raise TimeoutError(f"No se recibió ACK de {expected_from!r}")
        finally:
            self.sock.settimeout(None)

    def send(self, recipient: bytes, message: bytes):
        """Envía mensaje con handshake completo a un peer."""
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise ValueError("Peer no encontrado en discovery")
        dest = (info['ip'], UDP_PORT)

        # 1) Header → espera ACK
        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=1,
        )
        self.sock.sendto(header, dest)
        self._wait_for_ack(recipient)

        # 2) Body → espera ACK
        self.sock.sendto(message, dest)
        self._wait_for_ack(recipient)

    def broadcast(self, message: bytes):
        """Envía un mensaje a todos los peers conocidos (excepto BROADCAST_UID)."""
        for peer_id, info in self.discovery.get_peers().items():
            if peer_id == BROADCAST_UID:
                continue
            try:
                self.send(peer_id, message)
            except Exception:
                # Si falla un peer, seguir con el siguiente
                continue

    def start_listening(self):
        """Pone a la escucha el socket para mensajes y archivos entrantes."""
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self):
        """Bucle infinito que procesa paquetes entrantes."""
        while True:
            data, addr = self.sock.recvfrom(4096)
            if len(data) < HEADER_SIZE:
                continue

            hdr = unpack_header(data[:HEADER_SIZE])

            # Discovery ping
            if hdr['op_code'] == 0:
                self.discovery.handle_echo(data, addr)
                continue

            # ACK handshake (reconocimiento del header o del body)
            self.sock.sendto(pack_response(0, self.user_id), addr)
            initial_body = data[HEADER_SIZE:]
            threading.Thread(
                target=self._handle_message_or_file,
                args=(hdr, initial_body, addr),
                daemon=True
            ).start()

    def _handle_message_or_file(self, hdr, data: bytes, addr):
        peer_id = hdr['user_from']

        if hdr['op_code'] == 1:
            # Mensaje de texto
            text = data.decode('utf-8')
            self.history_store.append_message(
                sender=peer_id.decode('utf-8').rstrip('\x00'),
                recipient=self.user_id.decode('utf-8').rstrip('\x00'),
                message=text,
                timestamp=datetime.utcnow()
            )

        elif hdr['op_code'] == 2:
            # Archivo
            name_len = int.from_bytes(data[:2], 'big')
            filename = data[2:2 + name_len].decode('utf-8')
            file_data = data[2 + name_len:]
            os.makedirs('received_files', exist_ok=True)
            path = os.path.join('received_files', filename)
            with open(path, 'wb') as f:
                f.write(file_data)
            self.history_store.append_file(
                sender=peer_id.decode('utf-8').rstrip('\x00'),
                recipient=self.user_id.decode('utf-8').rstrip('\x00'),
                filename=filename,
                path=path,
                timestamp=datetime.utcnow()
            )

        # ACK final tras procesar mensaje o archivo
        self.sock.sendto(pack_response(0, self.user_id), addr)
