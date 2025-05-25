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
    Handshake: HEADER → ACK → BODY → ACK.
    """

    def __init__(self, user_id: bytes, discovery, history_store):
        # Aseguramos padding de 20 bytes en el UID
        self.user_id = user_id.rstrip(b'\x00').ljust(20, b'\x00')
        self.discovery = discovery
        self.history_store = history_store
        # Reutilizamos el socket configurado en discovery
        self.sock = discovery.sock

    def _wait_for_ack(self, expected_from: bytes, timeout: float = 2.0):
        """
        Espera un ACK válido con timeout.
        Ignora datagramas que no sean de tamaño RESPONSE_SIZE,
        o cuyo unpack_response falle, o cuyo status!=0,
        o cuyo responder!=expected_from.
        """
        self.sock.settimeout(timeout)
        try:
            while True:
                data, _ = self.sock.recvfrom(4096)
                # 1) Filtrar por tamaño exacto de un ACK
                if len(data) != RESPONSE_SIZE:
                    continue
                # 2) Intentar desempaquetar
                try:
                    resp = unpack_response(data)
                except Exception:
                    continue
                # 3) Validar status y peer
                if resp['status'] == 0 and resp['responder'] == expected_from.rstrip(b'\x00'):
                    return
        except socket.timeout:
            raise TimeoutError(f"No se recibió ACK de {expected_from!r}")
        finally:
            self.sock.settimeout(None)

    def send(self, recipient: bytes, message: bytes):
        """
        Envía un mensaje con handshake completo:
        1) HEADER(op_code=1, body_len=len(message)) → espera ACK
        2) BODY (payload) → espera ACK
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
        """
        Envía el mismo mensaje a todos los peers conocidos
        (salta al BROADCAST_UID).
        """
        for peer_id, info in self.discovery.get_peers().items():
            if peer_id == BROADCAST_UID:
                continue
            try:
                self.send(peer_id, message)
            except Exception:
                continue

    def start_listening(self):
        """Arranca el bucle de recepción en un hilo daemon."""
        threading.Thread(target=self.recv_loop, daemon=True).start()

    def recv_loop(self):
        """
        Bucle infinito:
        1) Recibe cabecera → ACK
        2) Recibe cuerpo   → ACK
        3) Despacha a handler
        """
        while True:
            # --- FASE 1: recibir HEADER ---
            header_data, addr = self.sock.recvfrom(4096)
            if len(header_data) < HEADER_SIZE:
                continue
            hdr = unpack_header(header_data)

            # Discovery ping (op_code == 0)
            if hdr['op_code'] == 0:
                self.discovery.handle_echo(header_data, addr)
                continue

            # ACK de la cabecera
            self.sock.sendto(pack_response(0, self.user_id), addr)

            # --- FASE 2: recibir BODY ---
            # body_len llegó en hdr['body_len']
            total = hdr.get('body_len', 0)
            body = b''
            while len(body) < total:
                chunk, _ = self.sock.recvfrom(4096)
                body += chunk

            # ACK del cuerpo
            self.sock.sendto(pack_response(0, self.user_id), addr)

            # Despachar el mensaje o archivo
            threading.Thread(
                target=self._handle_message_or_file,
                args=(hdr, body, addr),
                daemon=True
            ).start()

    def _handle_message_or_file(self, hdr, data: bytes, addr):
        peer_id = hdr['user_from'].rstrip(b'\x00')

        if hdr['op_code'] == 1:
            # Mensaje de texto
            text = data.decode('utf-8', errors='ignore')
            self.history_store.append_message(
                sender=peer_id.decode('utf-8'),
                recipient=self.user_id.rstrip(b'\x00').decode('utf-8'),
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
                sender=peer_id.decode('utf-8'),
                recipient=self.user_id.rstrip(b'\x00').decode('utf-8'),
                filename=filename,
                path=path,
                timestamp=datetime.utcnow()
            )
       

