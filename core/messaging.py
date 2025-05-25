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
    Comunicación con protocolo LCP (Header→ACK→Body→ACK).
    Sólo procesa paquetes de texto (op_code=1) o archivo (op_code=2)
    dirigidos a este peer.
    """

    def __init__(self, user_id: bytes, discovery, history_store):
        # Normalizar: UID útil sin nulls, luego relleno a 20 bytes para el protocolo
        trimmed = user_id.rstrip(b'\x00')
        self.user_id = trimmed.ljust(20, b'\x00')
        self.discovery = discovery
        self.history_store = history_store
        # Reutilizamos el socket de discovery
        self.sock = discovery.sock

    def _wait_for_ack(self, expected_from: bytes, timeout: float = 2.0):
        """
        Espera un ACK (RESPONSE_SIZE) con status==0 y responder==expected_from.
        Filtra todo lo demás.
        """
        self.sock.settimeout(timeout)
        try:
            while True:
                data, _ = self.sock.recvfrom(4096)
                if len(data) != RESPONSE_SIZE:
                    continue
                try:
                    resp = unpack_response(data)
                except Exception:
                    continue
                # Comparar sin padding
                if (
                    resp['status'] == 0 and
                    resp['responder'].rstrip(b'\x00') == expected_from.rstrip(b'\x00')
                ):
                    return
        except socket.timeout:
            raise TimeoutError(f"No se recibió ACK de {expected_from!r}")
        finally:
            self.sock.settimeout(None)

    def send(self, recipient: bytes, message: bytes):
        """
        Handshake de envío:
         1) Header(op_code=1, body_len) → ACK
         2) Body            → ACK
        """
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise ValueError("Peer no encontrado en discovery")
        dest = (info['ip'], UDP_PORT)

        # 1) Header
        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=1,
            body_id=0,
            body_len=len(message)
        )
        self.sock.sendto(header, dest)
        self._wait_for_ack(recipient)

        # 2) Body
        self.sock.sendto(message, dest)
        self._wait_for_ack(recipient)

    def broadcast(self, message: bytes):
        """Envía a todos los peers (salta BROADCAST_UID)."""
        for peer_id, info in self.discovery.get_peers().items():
            if peer_id == BROADCAST_UID:
                continue
            try:
                self.send(peer_id, message)
            except Exception:
                # Si falla uno, seguimos con el siguiente
                continue

    def start_listening(self):
        """Inicia el bucle de recepción en segundo plano."""
        threading.Thread(target=self.recv_loop, daemon=True).start()

    def recv_loop(self):
        """
        Bucle infinito:
         - Recibe HEADER (HEADER_SIZE) → si op_code==0 y user_to==BROADCAST_UID, discovery.handle_echo
                                 → si op_code!=0 y user_to==mi UID, ACK header, recibir body, ACK body, despachar.
         - Ignora todo lo demás.
        """
        while True:
            data, addr = self.sock.recvfrom(4096)
            if len(data) < HEADER_SIZE:
                continue

            hdr = unpack_header(data[:HEADER_SIZE])

            # Discovery ping
            if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                self.discovery.handle_echo(data, addr)
                continue

            # Sólo manejamos mensajes o archivos dirigidos a mí
            if hdr['op_code'] in (1, 2):
                if hdr['user_to'].rstrip(b'\x00') != self.user_id.rstrip(b'\x00'):
                    continue

                # ACK del header
                self.sock.sendto(pack_response(0, self.user_id), addr)

                # Recibimos UNA sola vez el cuerpo completo
                body, _ = self.sock.recvfrom(4096)

                # ACK del body
                self.sock.sendto(pack_response(0, self.user_id), addr)

                # Despachamos el manejo en hilo aparte
                threading.Thread(
                    target=self._handle_message_or_file,
                    args=(hdr, body, addr),
                    daemon=True
                ).start()

    def _handle_message_or_file(self, hdr, data: bytes, addr):
        peer_id = hdr['user_from'].rstrip(b'\x00').decode('utf-8')
        me_id   = self.user_id.rstrip(b'\x00').decode('utf-8')

        if hdr['op_code'] == 1:
            # Texto: recortar nulls y decodificar
            text = data.rstrip(b'\x00').decode('utf-8', errors='ignore')
            self.history_store.append_message(
                sender=peer_id,
                recipient=me_id,
                message=text,
                timestamp=datetime.utcnow()
            )

        elif hdr['op_code'] == 2:
            # Archivo: leer nombre + contenido
            name_len = int.from_bytes(data[:2], 'big')
            filename = data[2:2 + name_len].decode('utf-8', errors='ignore')
            file_data = data[2 + name_len:]
            os.makedirs('received_files', exist_ok=True)
            path = os.path.join('received_files', filename)
            with open(path, 'wb') as f:
                f.write(file_data)
            self.history_store.append_file(
                sender=peer_id,
                recipient=me_id,
                filename=filename,
                path=path,
                timestamp=datetime.utcnow()
            )
