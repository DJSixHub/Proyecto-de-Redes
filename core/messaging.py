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
    Soporta envío de texto y archivos, y guarda los archivos recibidos
    en ./Descargas en la raíz del proyecto.
    """

    def __init__(self, user_id: bytes, discovery, history_store):
        trimmed = user_id.rstrip(b'\x00')
        self.user_id = trimmed.ljust(20, b'\x00')
        self.discovery = discovery
        self.history_store = history_store

        self.sock = discovery.sock
        self.sock.setblocking(True)
        self.sock.settimeout(None)

        # Para coordinar ACKs que esperan send()/send_file()
        self._acks = {}             # responder_uid -> threading.Event
        self._acks_lock = threading.Lock()

    def _send_and_wait(self, data: bytes, recipient: bytes, timeout: float = 2.0):
        """
        Envía `data` a `recipient` y espera el ACK correspondiente.
        """
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise ValueError("Peer no encontrado en discovery")
        dest = (info['ip'], UDP_PORT)

        ev = threading.Event()
        key = recipient.rstrip(b'\x00')
        with self._acks_lock:
            self._acks[key] = ev

        self.sock.sendto(data, dest)
        received = ev.wait(timeout)

        with self._acks_lock:
            self._acks.pop(key, None)

        if not received:
            raise TimeoutError(f"No se recibió ACK de {recipient!r}")

    def send(self, recipient: bytes, message: bytes, timeout: float = 2.0):
        """
        Envía un mensaje de texto:
          1) HEADER(op_code=1, body_len) → ACK
          2) BODY(message)               → ACK
        """
        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=1,
            body_id=0,
            body_len=len(message)
        )
        self._send_and_wait(header, recipient, timeout)
        self._send_and_wait(message, recipient, timeout)

    def send_file(self, recipient: bytes, file_bytes: bytes, filename: str, timeout: float = 5.0):
        """
        Envía un archivo:
          1) HEADER(op_code=2, body_len) → ACK
          2) BODY(2B name_len + filename + file_bytes) → ACK
        """
        name_b = filename.encode('utf-8')
        if len(name_b) > 0xFFFF:
            raise ValueError("Nombre de archivo demasiado largo")
        body = len(name_b).to_bytes(2, 'big') + name_b + file_bytes

        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=2,
            body_id=0,
            body_len=len(body)
        )
        self._send_and_wait(header, recipient, timeout)
        self._send_and_wait(body, recipient, timeout)

    def broadcast(self, message: bytes):
        """Envía un mensaje de texto a todos los peers (excepto BROADCAST_UID)."""
        for peer_id in self.discovery.get_peers():
            if peer_id == BROADCAST_UID:
                continue
            try:
                self.send(peer_id, message)
            except:
                pass

    def send_all(self, message: bytes):
        """Alias para compatibilidad: envía un mensaje de texto global."""
        return self.broadcast(message)

    def start_listening(self):
        threading.Thread(target=self.recv_loop, daemon=True).start()

    def recv_loop(self):
        while True:
            data, addr = self.sock.recvfrom(4096)

            # 1) ¿Es un ACK?
            if len(data) == RESPONSE_SIZE:
                try:
                    resp = unpack_response(data)
                except:
                    continue
                if resp['status'] == 0:
                    r = resp['responder'].rstrip(b'\x00')
                    with self._acks_lock:
                        ev = self._acks.get(r)
                    if ev:
                        ev.set()
                        continue
                self.discovery.handle_response(data, addr)
                continue

            # 2) Mensaje o archivo (cabecera)
            if len(data) < HEADER_SIZE:
                continue

            hdr = unpack_header(data[:HEADER_SIZE])

            # Discovery ping
            if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                self.discovery.handle_echo(data, addr)
                continue

            # Sólo procesar si es para mí
            if hdr['op_code'] in (1, 2) and hdr['user_to'].rstrip(b'\x00') == self.user_id.rstrip(b'\x00'):
                # ACK cabecera
                self.sock.sendto(pack_response(0, self.user_id), addr)

                # Recibir cuerpo completo
                body_len = hdr['body_len']
                chunk, _ = self.sock.recvfrom(max(body_len, 4096))
                body = chunk[:body_len]

                # ACK cuerpo
                self.sock.sendto(pack_response(0, self.user_id), addr)

                # Despachar
                threading.Thread(
                    target=self._handle_message_or_file,
                    args=(hdr, body),
                    daemon=True
                ).start()

    def _handle_message_or_file(self, hdr, body: bytes):
        peer = hdr['user_from'].rstrip(b'\x00').decode('utf-8', errors='ignore')
        me   = self.user_id.rstrip(b'\x00').decode('utf-8')

        if hdr['op_code'] == 1:
            # Texto
            text = body.decode('utf-8', errors='ignore').rstrip('\x00')
            self.history_store.append_message(
                sender=peer,
                recipient=me,
                message=text,
                timestamp=datetime.utcnow()
            )
        else:
            # Archivo: guardar en carpeta "Descargas"
            name_len = int.from_bytes(body[:2], 'big')
            filename = body[2:2 + name_len].decode('utf-8', errors='ignore')
            file_data = body[2 + name_len:]

            downloads_dir = os.path.join(os.getcwd(), "Descargas")
            os.makedirs(downloads_dir, exist_ok=True)
            path = os.path.join(downloads_dir, filename)
            with open(path, 'wb') as f:
                f.write(file_data)

            self.history_store.append_file(
                sender=peer,
                recipient=me,
                filename=filename,
                timestamp=datetime.utcnow()
            )
