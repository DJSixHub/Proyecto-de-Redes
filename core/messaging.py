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
    Usa un solo reader (recv_loop) y una cola de ACKs
    para que send() nunca compita en recvfrom().
    """

    def __init__(self, user_id: bytes, discovery, history_store):
        # Normalizar UID a 20 bytes
        trimmed = user_id.rstrip(b'\x00')
        self.user_id = trimmed.ljust(20, b'\x00')
        self.discovery = discovery
        self.history_store = history_store

        # Reutiliza el socket de discovery
        self.sock = discovery.sock
        self.sock.setblocking(True)
        self.sock.settimeout(None)

        # Estructura para coordinar ACKs
        self._acks = {}             # responder_uid (bytes sin \x00) -> threading.Event
        self._acks_lock = threading.Lock()

    def send(self, recipient: bytes, message: bytes, timeout: float = 2.0):
        """
        Envía un mensaje con handshake completo:
          1) HEADER → espera ACK
          2) BODY   → espera ACK
        Levanta TimeoutError si no llega ACK.
        """
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise ValueError("Peer no encontrado en discovery")
        dest = (info['ip'], UDP_PORT)

        # Helper local para registrar y esperar ACK
        def _send_and_wait(data: bytes):
            ev = threading.Event()
            key = recipient.rstrip(b'\x00')
            with self._acks_lock:
                self._acks[key] = ev
            self.sock.sendto(data, dest)
            ok = ev.wait(timeout)
            with self._acks_lock:
                self._acks.pop(key, None)
            if not ok:
                raise TimeoutError(f"No se recibió ACK de {recipient!r}")

        # 1) Header
        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=1,
            body_id=0,
            body_len=len(message)
        )
        _send_and_wait(header)

        # 2) Body
        _send_and_wait(message)

    def broadcast(self, message: bytes):
        """Envía el mismo mensaje a todos los peers (salta BROADCAST_UID)."""
        for peer_id, info in self.discovery.get_peers().items():
            if peer_id == BROADCAST_UID:
                continue
            try:
                self.send(peer_id, message)
            except Exception:
                pass

    def start_listening(self):
        """Arranca recv_loop en hilo daemon."""
        threading.Thread(target=self.recv_loop, daemon=True).start()

    def recv_loop(self):
        """
        Lee TODO del socket:
         - Si len==RESPONSE_SIZE: desempaqueta ACK y lo despacha a quien lo espera.
         - Si len>=HEADER_SIZE: procesa discovery o mensaje (header+body).
        """
        while True:
            data, addr = self.sock.recvfrom(4096)

            # --- 1) Posible ACK ---
            if len(data) == RESPONSE_SIZE:
                try:
                    resp = unpack_response(data)
                except Exception:
                    continue
                if resp['status'] == 0:
                    responder = resp['responder'].rstrip(b'\x00')
                    with self._acks_lock:
                        ev = self._acks.get(responder)
                    if ev:
                        ev.set()
                        continue
                # si no era un ACK que esperábamos, pasa a discovery:
                self.discovery.handle_response(data, addr)
                continue

            # --- 2) Mensaje o discovery (cabecera) ---
            if len(data) < HEADER_SIZE:
                continue

            hdr = unpack_header(data[:HEADER_SIZE])

            # Discovery ping
            if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                self.discovery.handle_echo(data, addr)
                continue

            # Mensaje o archivo dirigido a mí
            if hdr['op_code'] in (1, 2) and hdr['user_to'].rstrip(b'\x00') == self.user_id.rstrip(b'\x00'):
                # ACK de la cabecera
                self.sock.sendto(pack_response(0, self.user_id), addr)

                # Recibimos el cuerpo (un solo recv; luego cortamos al tamaño)
                body_len = hdr['body_len']
                chunk, _ = self.sock.recvfrom(max(body_len, 4096))
                body = chunk[:body_len]

                # ACK del cuerpo
                self.sock.sendto(pack_response(0, self.user_id), addr)

                # Despacha el manejo
                threading.Thread(
                    target=self._handle_message_or_file,
                    args=(hdr, body),
                    daemon=True
                ).start()

    def _handle_message_or_file(self, hdr, body: bytes):
        peer = hdr['user_from'].rstrip(b'\x00').decode('utf-8', errors='ignore')
        me   = self.user_id.rstrip(b'\x00').decode('utf-8')

        if hdr['op_code'] == 1:
            # Texto: decodificar y eliminar \x00 finales
            text = body.decode('utf-8', errors='ignore').rstrip('\x00')
            self.history_store.append_message(
                sender=peer,
                recipient=me,
                message=text,
                timestamp=datetime.utcnow()
            )

        elif hdr['op_code'] == 2:
            # Archivo: nombre + datos
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
