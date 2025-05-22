# core/discovery.py

import socket
import threading
import time
from datetime import datetime

from core.protocol import (
    UDP_PORT, BROADCAST_UID,
    pack_header, unpack_header,
    pack_response, unpack_response,
    HEADER_SIZE, RESPONSE_SIZE
)


class Discovery:
    """
    Lógica de broadcast continuo y recepción permanente de peers.
    Mantiene un diccionario self.peers = {
        uid_bytes: {'ip': str, 'last_seen': datetime}
    } y opcionalmente persiste en disco.
    """

    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0,
                 peers_store=None):
        self.user_id = user_id
        self.broadcast_interval = broadcast_interval
        self.peers_store = peers_store

        # Mapa interno de peers
        self.peers = {}

        # Socket UDP para broadcast y recepción
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(('', UDP_PORT))

        # Hilos de background
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        threading.Thread(target=self._recv_loop, daemon=True).start()
        if self.peers_store:
            threading.Thread(target=self._persist_loop, daemon=True).start()

    def _broadcast_loop(self):
        """Envía un Echo-Request de broadcast cada broadcast_interval."""
        while True:
            pkt = pack_header(self.user_id, BROADCAST_UID, op_code=0)
            self.sock.sendto(pkt, ('<broadcast>', UDP_PORT))
            time.sleep(self.broadcast_interval)

    def _recv_loop(self):
        """
        Bucle permanente de recepción:
        - Si recibe op_code=0: responde con pack_response.
        - En cualquier caso, actualiza self.peers con último visto.
        """
        while True:
            data, addr = self.sock.recvfrom(max(HEADER_SIZE, RESPONSE_SIZE))
            now = datetime.utcnow()

            # Responder a un Echo-Request
            if len(data) >= HEADER_SIZE:
                hdr = unpack_header(data)
                if hdr['op_code'] == 0:
                    resp = pack_response(0, self.user_id)
                    self.sock.sendto(resp, addr)
                peer_id = hdr['user_from']

            # Registrar también replies si llegan como RESPONSE_FMT
            if len(data) >= RESPONSE_SIZE:
                try:
                    resp = unpack_response(data)
                    peer_id = resp['responder']
                except:
                    pass

            # Actualizar o añadir peer
            self.peers[peer_id] = {
                'ip': addr[0],
                'last_seen': now
            }

    def _persist_loop(self):
        """Vuelca self.peers a disco cada 5 segundos si hay peers_store."""
        while True:
            time.sleep(5)
            self.peers_store.save(self.peers)

    def get_peers(self) -> dict:
        """Devuelve una copia del mapa actual de peers."""
        return self.peers.copy()
