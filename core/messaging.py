# core/messaging.py

import threading
import socket
import os
from datetime import datetime

from core.protocol import (
    UDP_PORT,
    pack_header, unpack_header,
    pack_response, unpack_response,
    HEADER_SIZE, RESPONSE_SIZE
)


class Messaging:
    """
    Envía y recibe mensajes y archivos siguiendo el protocolo:
     1. Enviar header    → esperar ACK
     2. Enviar body      → esperar ACK
     3. Procesar/guardar
    """

    def __init__(self,
                 user_id: bytes,
                 discovery,
                 history_store):
        self.user_id = user_id
        self.sock = discovery.sock
        self.discovery = discovery
        self.history_store = history_store

    def _wait_for_ack(self, expected_from: bytes, timeout: float = 2.0):
        """
        Espera un paquete RESPONSE_FMT y valida:
          - status == 0
          - responder == expected_from
        """
        self.sock.settimeout(timeout)
        try:
            data, _ = self.sock.recvfrom(RESPONSE_SIZE)
            resp = unpack_response(data)
            if resp['status'] != 0 or resp['responder'] != expected_from:
                raise ValueError("ACK inválido")
        finally:
            self.sock.settimeout(None)

    def send(self, recipient: bytes, message: bytes):
        """
        Enviar un mensaje de texto con handshake de header/body.
        """
        peers = self.discovery.get_peers()
        info = peers.get(recipient)
        if not info:
            raise ValueError("Peer no encontrado")

        dest = (info['ip'], UDP_PORT)

        # 1) Header
        header = pack_header(
            self.user_id,
            user_to=recipient,
            op_code=1,
            body_len=len(message)
        )
        self.sock.sendto(header, dest)
        self._wait_for_ack(expected_from=recipient)

        # 2) Body
        self.sock.sendto(message, dest)
        self._wait_for_ack(expected_from=recipient)

        # 3) Registrar en historial
        self.history_store.append_message(
            sender=self.user_id.decode('utf-8'),
            message=message.decode('utf-8'),
            timestamp=datetime.utcnow()
        )

    def send_file(self, recipient: bytes, file_path: str):
        """
        Enviar un archivo:
         - Header con nombre y tamaño
         - Body = bytes del archivo
        """
        peers = self.discovery.get_peers()
        info = peers.get(recipient)
        if not info:
            raise ValueError("Peer no encontrado")
        dest = (info['ip'], UDP_PORT)

        # Leer contenido
        filename = os.path.basename(file_path).encode('utf-8')
        with open(file_path, 'rb') as f:
            data = f.read()

        # Construir cuerpo inicial: filename_length(2 bytes) + filename
        name_hdr = len(filename).to_bytes(2, 'big') + filename

        # 1) Header op_code=2, body_len = len(name_hdr) + len(data)
        total_len = len(name_hdr) + len(data)
        header = pack_header(
            self.user_id,
            user_to=recipient,
            op_code=2,
            body_len=total_len
        )
        self.sock.sendto(header, dest)
        self._wait_for_ack(expected_from=recipient)

        # 2) Body: primero name_hdr, luego data
        self.sock.sendto(name_hdr + data, dest)
        self._wait_for_ack(expected_from=recipient)

        # 3) Registrar en historial
        self.history_store.append_file(
            sender=self.user_id.decode('utf-8'),
            filename=filename.decode('utf-8'),
            timestamp=datetime.utcnow()
        )

    def recv_loop(self):
        """
        Bucle permanente que distingue:
         - op_code=1 → texto
         - op_code=2 → archivo
        Aplica handshake inverso: ACK header, recv body, ACK body.
        """
        while True:
            # 1) Recibir header
            data, addr = self.sock.recvfrom(max(HEADER_SIZE, RESPONSE_SIZE))
            if len(data) < HEADER_SIZE:
                continue

            hdr = unpack_header(data[:HEADER_SIZE])
            sender = hdr['user_from']
            body_len = hdr['body_len']

            # ACK header
            ack = pack_response(0, self.user_id)
            self.sock.sendto(ack, addr)

            # 2) Recibir body completo
            received = b''
            while len(received) < body_len:
                chunk, _ = self.sock.recvfrom(body_len - len(received))
                received += chunk

            # ACK body
            self.sock.sendto(pack_response(0, self.user_id), addr)

            # 3) Procesar según op_code
            if hdr['op_code'] == 1:
                # Mensaje de texto
                text = received.decode('utf-8')
                self.history_store.append_message(
                    sender=sender.decode('utf-8'),
                    message=text,
                    timestamp=datetime.utcnow()
                )

            elif hdr['op_code'] == 2:
                # Archivo: primero 2 bytes nombre, luego nombre y datos
                name_len = int.from_bytes(received[:2], 'big')
                filename = received[2:2+name_len].decode('utf-8')
                file_data = received[2+name_len:]

                # Guardar en disco (puede ajustarse la carpeta)
                save_path = os.path.join('received_files', filename)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, 'wb') as f:
                    f.write(file_data)

                self.history_store.append_file(
                    sender=sender.decode('utf-8'),
                    filename=filename,
                    timestamp=datetime.utcnow()
                )

            # Ignorar otros op_codes
