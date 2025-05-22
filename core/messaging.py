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
        self.sock = discovery.sock

    def _wait_for_ack(self, expected_from: bytes, timeout: float = 2.0):
        """Espera un ACK válido, con timeout."""
        self.sock.settimeout(timeout)
        try:
            data, _ = self.sock.recvfrom(4096)
            resp = unpack_response(data[:RESPONSE_SIZE])
            if resp['status'] != 0 or resp['responder'] != expected_from:
                raise ValueError(f"ACK inválido: {resp}")
        finally:
            self.sock.settimeout(None)

    def send(self, recipient: bytes, message: bytes):
        """Envía mensaje con handshake completo a un peer."""
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise ValueError("Peer no encontrado en discovery")
        dest = (info['ip'], UDP_PORT)

        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=1,
            body_len=len(message)
        )
        self.sock.sendto(header, dest)
        self._wait_for_ack(expected_from=recipient)

        self.sock.sendto(message, dest)
        self._wait_for_ack(expected_from=recipient)

        self.history_store.append_message(
            sender=self.user_id.decode('utf-8').rstrip('\x00'),
            recipient=recipient.decode('utf-8').rstrip('\x00'),
            message=message.decode('utf-8'),
            timestamp=datetime.utcnow()
        )

    def send_all(self, message: bytes):
        """
        Envía mensaje a todos los peers conocidos siguiendo protocolo completo.
        Header → ACK → Body → ACK por cada uno.
        """
        for recipient, info in self.discovery.get_peers().items():
            dest = (info['ip'], UDP_PORT)

            header = pack_header(
                user_from=self.user_id,
                user_to=recipient,
                op_code=1,
                body_len=len(message)
            )
            self.sock.sendto(header, dest)
            self._wait_for_ack(expected_from=recipient)

            self.sock.sendto(message, dest)
            self._wait_for_ack(expected_from=recipient)

            self.history_store.append_message(
                sender=self.user_id.decode('utf-8').rstrip('\x00'),
                recipient=recipient.decode('utf-8').rstrip('\x00'),
                message=message.decode('utf-8'),
                timestamp=datetime.utcnow()
            )

    def send_file(self, recipient: bytes, file_path: str):
        """Envía archivo binario con nombre, usando handshake completo."""
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise ValueError("Peer no encontrado")
        dest = (info['ip'], UDP_PORT)

        filename = os.path.basename(file_path).encode('utf-8')
        with open(file_path, 'rb') as f:
            file_data = f.read()
        name_hdr = len(filename).to_bytes(2, 'big') + filename
        total_len = len(name_hdr) + len(file_data)

        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=2,
            body_len=total_len
        )
        self.sock.sendto(header, dest)
        self._wait_for_ack(expected_from=recipient)

        self.sock.sendto(name_hdr + file_data, dest)
        self._wait_for_ack(expected_from=recipient)

        self.history_store.append_file(
            sender=self.user_id.decode('utf-8').rstrip('\x00'),
            recipient=recipient.decode('utf-8').rstrip('\x00'),
            filename=filename.decode('utf-8'),
            timestamp=datetime.utcnow()
        )

    def _handle_message_or_file(self, hdr, initial_data: bytes, addr):
        """Procesa body de mensaje o archivo tras recibir header + ACK."""
        peer_id = hdr['user_from']
        body_len = hdr['body_len']
        data = initial_data
        while len(data) < body_len:
            chunk, _ = self.sock.recvfrom(body_len - len(data))
            data += chunk

        # ACK final tras recibir body completo
        self.sock.sendto(pack_response(0, self.user_id), addr)

        if hdr['op_code'] == 1:
            text = data.decode('utf-8')
            self.history_store.append_message(
                sender=peer_id.decode('utf-8').rstrip('\x00'),
                recipient=self.user_id.decode('utf-8').rstrip('\x00'),
                message=text,
                timestamp=datetime.utcnow()
            )
        elif hdr['op_code'] == 2:
            name_len = int.from_bytes(data[:2], 'big')
            filename = data[2:2 + name_len].decode('utf-8')
            file_data = data[2 + name_len:]
            os.makedirs("received_files", exist_ok=True)
            with open(os.path.join("received_files", filename), 'wb') as f:
                f.write(file_data)
            self.history_store.append_file(
                sender=peer_id.decode('utf-8').rstrip('\x00'),
                recipient=self.user_id.decode('utf-8').rstrip('\x00'),
                filename=filename,
                timestamp=datetime.utcnow()
            )

    def recv_loop(self):
        """Escucha datagramas entrantes y despacha su tipo."""
        while True:
            data, addr = self.sock.recvfrom(max(HEADER_SIZE, RESPONSE_SIZE, 4096))

            if len(data) == RESPONSE_SIZE:
                self.discovery.handle_response(data, addr)
                continue

            if len(data) >= HEADER_SIZE:
                hdr = unpack_header(data[:HEADER_SIZE])

                if hdr['op_code'] == 0:
                    self.discovery.handle_echo(data, addr)
                    continue

                self.sock.sendto(pack_response(0, self.user_id), addr)
                initial_body = data[HEADER_SIZE:]
                threading.Thread(
                    target=self._handle_message_or_file,
                    args=(hdr, initial_body, addr),
                    daemon=True
                ).start()
