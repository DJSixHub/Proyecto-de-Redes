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
    Comunicación con protocolo LCP (HEADER → ACK → BODY → ACK).
    Sólo procesa op_code 1 (mensaje) y 2 (archivo) dirigidos a este peer.
    """

    def __init__(self, user_id: bytes, discovery, history_store):
        # Normalizar el UID a 20 bytes
        trimmed = user_id.rstrip(b'\x00')
        self.user_id = trimmed.ljust(20, b'\x00')
        self.discovery = discovery
        self.history_store = history_store

        # Reutilizamos el socket de discovery y lo dejamos en modo blocking
        self.sock = discovery.sock
        self.sock.settimeout(None)
        self.sock.setblocking(True)

    def send(self, recipient: bytes, message: bytes):
        """
        Envía un mensaje con handshake completo:
        1) Cabecera (op_code=1, body_len) → espera ACK
        2) Cuerpo (payload)               → espera ACK
        """
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise ValueError("Peer no encontrado en discovery")
        dest = (info['ip'], UDP_PORT)

        # 1) Empaquetar y enviar cabecera
        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=1,
            body_id=0,
            body_len=len(message)
        )
        self.sock.sendto(header, dest)
        self._wait_for_ack(recipient)

        # 2) Enviar el cuerpo
        self.sock.sendto(message, dest)
        self._wait_for_ack(recipient)

    def _wait_for_ack(self, expected_from: bytes, timeout: float = 2.0):
        """
        Espera un ACK (RESPONSE_SIZE bytes) con status==0
        y responder==expected_from. Ignora todo lo demás.
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
                if (resp['status'] == 0
                    and resp['responder'] == expected_from.rstrip(b'\x00')):
                    return
        except socket.timeout:
            raise TimeoutError(f"No se recibió ACK de {expected_from!r}")
        finally:
            self.sock.settimeout(None)

    def recv_loop(self):
        """
        Bucle principal de recepción:
         - Si llega un RESPONSE_SIZE → handle_response (Discovery)
         - Si llega >= HEADER_SIZE → desempacar cabecera
             • op_code=0 y user_to=BROADCAST_UID → handle_echo
             • op_code∈{1,2} y user_to==mi UID   → handshake de cuerpo + dispatch
        """
        while True:
            data, addr = self.sock.recvfrom(4096)

            # 1) Discovery: Echo-Replies y ACKs de messaging
            if len(data) == RESPONSE_SIZE:
                self.discovery.handle_response(data, addr)
                continue

            # 2) Paquetes demasiado cortos
            if len(data) < HEADER_SIZE:
                continue

            # 3) Desempaquetar cabecera
            hdr = unpack_header(data[:HEADER_SIZE])

            # 3a) Discovery: Broadcast de ping
            if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                self.discovery.handle_echo(data, addr)
                continue

            # 3b) Mensajería: sólo si va dirigido a mí
            if hdr['op_code'] in (1, 2) and hdr['user_to'] == self.user_id.rstrip(b'\x00'):
                # ACK de la cabecera
                self.sock.sendto(pack_response(0, self.user_id), addr)

                # Leer el cuerpo (esperamos que quepa en un solo recv)
                body_len = hdr['body_len']
                body_data, _ = self.sock.recvfrom(max(body_len, 4096))
                # Cortar a la longitud exacta
                body = body_data[:body_len]

                # ACK del cuerpo
                self.sock.sendto(pack_response(0, self.user_id), addr)

                # Despachar en un hilo para procesar texto o archivo
                threading.Thread(
                    target=self._handle_message_or_file,
                    args=(hdr, body, addr),
                    daemon=True
                ).start()

    def _handle_message_or_file(self, hdr, body: bytes, addr):
        peer = hdr['user_from'].rstrip(b'\x00').decode('utf-8')
        me   = self.user_id.rstrip(b'\x00').decode('utf-8')

        if hdr['op_code'] == 1:
            # Mensaje de texto: decodificar y recortar nulls
            text = body.decode('utf-8', errors='ignore').rstrip('\x00')
            self.history_store.append_message(
                sender=peer,
                recipient=me,
                message=text,
                timestamp=datetime.utcnow()
            )

        elif hdr['op_code'] == 2:
            # Archivo: primero longitud del nombre, luego datos
            name_len = int.from_bytes(body[:2], 'big')
            filename = body[2:2 + name_len].decode('utf-8', errors='ignore')
            file_data = body[2 + name_len:]
            os.makedirs('received_files', exist_ok=True)
            path = os.path.join('received_files', filename)
            with open(path, 'wb') as f:
                f.write(file_data)
            self.history_store.append_file(
                sender=peer,
                recipient=me,
                filename=filename,
                path=path,
                timestamp=datetime.utcnow()
            )

    def start_listening(self):
        """Arranca recv_loop en un hilo daemon."""
        threading.Thread(target=self.recv_loop, daemon=True).start()
