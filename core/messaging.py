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
    Envía y recibe mensajes y archivos siguiendo el protocolo:
      1) send: header → ACK → body → ACK
      2) send_file: header → ACK → body → ACK
      3) send_all: único broadcast de header+body (op_code=1)
    La recepción es concurrente: cada datagrama se procesa en un hilo.
    """

    def __init__(self, user_id: bytes, discovery, history_store):
        self.user_id = user_id
        self.sock = discovery.sock
        self.discovery = discovery
        self.history_store = history_store

    def _wait_for_ack(self, expected_from: bytes, timeout: float = 2.0):
        """Espera un paquete RESPONSE_FMT válido de expected_from."""
        self.sock.settimeout(timeout)
        try:
            data, _ = self.sock.recvfrom(RESPONSE_SIZE)
            resp = unpack_response(data)
            if resp['status'] != 0 or resp['responder'] != expected_from:
                raise ValueError("ACK inválido")
        finally:
            self.sock.settimeout(None)

    def send(self, recipient: bytes, message: bytes):
        """Envía un mensaje de texto con handshake de header y body."""
        peers = self.discovery.get_peers()
        info = peers.get(recipient)
        if not info:
            raise ValueError("Peer no encontrado")

        dest = (info['ip'], UDP_PORT)

        # 1) Header
        header = pack_header(
            user_from=self.user_id,
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
        """Envía un archivo con handshake de header y body."""
        peers = self.discovery.get_peers()
        info = peers.get(recipient)
        if not info:
            raise ValueError("Peer no encontrado")

        dest = (info['ip'], UDP_PORT)

        # Leer y preparar contenido
        filename = os.path.basename(file_path).encode('utf-8')
        with open(file_path, 'rb') as f:
            data = f.read()
        name_hdr = len(filename).to_bytes(2, 'big') + filename
        total_len = len(name_hdr) + len(data)

        # 1) Header op_code=2
        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=2,
            body_len=total_len
        )
        self.sock.sendto(header, dest)
        self._wait_for_ack(expected_from=recipient)

        # 2) Body: nombre + datos
        self.sock.sendto(name_hdr + data, dest)
        self._wait_for_ack(expected_from=recipient)

        # 3) Registrar en historial
        self.history_store.append_file(
            sender=self.user_id.decode('utf-8'),
            filename=filename.decode('utf-8'),
            timestamp=datetime.utcnow()
        )

    def send_all(self, message: bytes):
        """
        Envía un mensaje de texto a todos los peers usando BROADCAST_UID.
        No espera ACKs.
        """
        header = pack_header(
            user_from=self.user_id,
            user_to=BROADCAST_UID,
            op_code=1,
            body_len=len(message)
        )
        pkt = header + message
        self.sock.sendto(pkt, ('<broadcast>', UDP_PORT))

        # Registrar localmente cada envío como propio
        for peer_id in self.discovery.get_peers().keys():
            self.history_store.append_message(
                sender=self.user_id.decode('utf-8'),
                message=message.decode('utf-8'),
                timestamp=datetime.utcnow()
            )

    def _handle_incoming(self, data: bytes, addr):
        """
        Procesa un paquete entrante:
          a) ACK del header
          b) leer body completo
          c) ACK del body
          d) guardar mensaje o archivo
        """
        if len(data) < HEADER_SIZE:
            return

        hdr = unpack_header(data[:HEADER_SIZE])
        peer_id = hdr['user_from']

        # ACK del header
        self.sock.sendto(pack_response(0, self.user_id), addr)

        # Leer body
        body_len = hdr['body_len']
        received = b''
        while len(received) < body_len:
            chunk, _ = self.sock.recvfrom(body_len - len(received))
            received += chunk

        # ACK del body
        self.sock.sendto(pack_response(0, self.user_id), addr)

        # Procesar contenido
        if hdr['op_code'] == 1:
            # Mensaje de texto
            text = received.decode('utf-8')
            self.history_store.append_message(
                sender=peer_id.decode('utf-8'),
                message=text,
                timestamp=datetime.utcnow()
            )

        elif hdr['op_code'] == 2:
            # Archivo: 2 bytes de longitud de nombre + nombre + datos
            name_len = int.from_bytes(received[:2], 'big')
            filename = received[2:2 + name_len].decode('utf-8')
            file_data = received[2 + name_len:]

            # Guardar en disco
            save_dir = 'received_files'
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, filename)
            with open(save_path, 'wb') as f:
                f.write(file_data)

            self.history_store.append_file(
                sender=peer_id.decode('utf-8'),
                filename=filename,
                timestamp=datetime.utcnow()
            )

    def recv_loop(self):
        """Bucle permanente de recepción que lanza hilos por paquete."""
        while True:
            data, addr = self.sock.recvfrom(max(HEADER_SIZE, RESPONSE_SIZE))
            threading.Thread(
                target=self._handle_incoming,
                args=(data, addr),
                daemon=True
            ).start()
