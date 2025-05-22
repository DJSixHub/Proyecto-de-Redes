# core/discovery.py

import socket
import time
import threading
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

OFFLINE_THRESHOLD = 20.0  # segundos para considerar un peer desconectado

class Discovery:
    """
    Envía Echo-Request periódicos y mantiene el mapa de peers.
    Procesa:
      - Echo-Request (op_code=0) → handle_echo()
      - Echo-Reply (RESPONSE_FMT)   → handle_response()
    Antes de persistir, añade campo 'status' = 'connected'|'disconnected'
    según last_seen.
    """

    def __init__(self, user_id: bytes, broadcast_interval: float = 1.0,
                 peers_store=None):
        self.raw_id = user_id.rstrip(b'\x00')
        self.user_id = self.raw_id.ljust(20, b'\x00')
        self.broadcast_interval = broadcast_interval
        self.peers_store = peers_store

        # IP local para filtrar
        hostname = socket.gethostname()
        self.local_ip = socket.gethostbyname(hostname)

        # Mapa interno: raw_peer_id → {'ip', 'last_seen': datetime}
        self.peers = {}

        # Socket UDP escuchando todas las interfaces
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(('', UDP_PORT))

        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        if self.peers_store:
            threading.Thread(target=self._persist_loop, daemon=True).start()

    def _broadcast_loop(self):
        while True:
            pkt = pack_header(self.user_id, BROADCAST_UID, op_code=0)
            self.sock.sendto(pkt, ('<broadcast>', UDP_PORT))
            time.sleep(self.broadcast_interval)

    def _persist_loop(self):
        """
        Cada 5s calcula status según last_seen y persiste:
        { raw_peer_id: {'ip','last_seen','status'} }
        """
        while True:
            time.sleep(5)
            now = datetime.utcnow()
            to_save = {}
            for uid, info in self.peers.items():
                age = (now - info['last_seen']).total_seconds()
                status = 'connected' if age < OFFLINE_THRESHOLD else 'disconnected'
                to_save[uid] = {
                    'ip': info['ip'],
                    'last_seen': info['last_seen'],
                    'status': status
                }
            self.peers_store.save(to_save)

    def handle_echo(self, data: bytes, addr):
        hdr = unpack_header(data[:HEADER_SIZE])
        peer_id = hdr['user_from'].rstrip(b'\x00')
        peer_ip = addr[0]
        if peer_id == self.raw_id or peer_ip == self.local_ip:
            return
        # responder
        self.sock.sendto(pack_response(0, self.user_id), addr)
        # eliminar UID viejo para esa IP
        for uid in list(self.peers):
            if self.peers[uid]['ip'] == peer_ip and uid != peer_id:
                del self.peers[uid]
        # registrar/actualizar
        self.peers[peer_id] = {'ip': peer_ip, 'last_seen': datetime.utcnow()}

    def handle_response(self, data: bytes, addr):
        resp = unpack_response(data[:RESPONSE_SIZE])
        peer_id = resp['responder'].rstrip(b'\x00')
        peer_ip = addr[0]
        if resp['status'] != 0 or peer_id == self.raw_id or peer_ip == self.local_ip:
            return
        # eliminar UID viejo para esa IP
        for uid in list(self.peers):
            if self.peers[uid]['ip'] == peer_ip and uid != peer_id:
                del self.peers[uid]
        # registrar/actualizar
        self.peers[peer_id] = {'ip': peer_ip, 'last_seen': datetime.utcnow()}

    def get_peers(self) -> dict:
        return self.peers.copy()
