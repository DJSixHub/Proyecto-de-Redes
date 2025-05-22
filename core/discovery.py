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

OFFLINE_THRESHOLD = 20.0  # segundos antes de considerar un peer desconectado

class Discovery:
    """
    Envía Echo-Request periódicos y mantiene el mapa de peers.
    Filtra automáticamente cualquier IP local de la máquina.
    Expone `local_ip` (IP principal) y `local_ips` (conjunto de todas las locales).
    """

    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0,
                 peers_store=None):
        # UID raw (sin padding) y padded (20 bytes)
        self.raw_id = user_id.rstrip(b'\x00')
        self.user_id = self.raw_id.ljust(20, b'\x00')
        self.broadcast_interval = broadcast_interval
        self.peers_store = peers_store

        # Determinar IP principal y todas las IPs locales
        hostname = socket.gethostname()
        all_addrs = socket.gethostbyname_ex(hostname)[2]
        # Elegimos la primera que no sea loopback como `local_ip`
        self.local_ip = next((ip for ip in all_addrs if not ip.startswith("127.")), all_addrs[0])
        # Conjunto de todas las IPs de la máquina, incluyendo loopback
        self.local_ips = set(all_addrs) | {"127.0.0.1"}

        # Mapa interno: raw_peer_id → {'ip', 'last_seen'}
        self.peers = {}

        # Socket UDP en todas las interfaces
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(('', UDP_PORT))

        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        if self.peers_store:
            threading.Thread(target=self._persist_loop, daemon=True).start()

    def _broadcast_loop(self):
        while True:
            self._do_broadcast()
            time.sleep(self.broadcast_interval)

    def _do_broadcast(self):
        pkt = pack_header(
            user_from=self.user_id,
            user_to=BROADCAST_UID,
            op_code=0
        )
        self.sock.sendto(pkt, ('<broadcast>', UDP_PORT))

    def force_discover(self):
        """Envía inmediatamente un broadcast de descubrimiento."""
        self._do_broadcast()

    def _persist_loop(self):
        """
        Cada 5s, filtra cualquier peer cuya IP sea local
        y persiste el resto con su estado conectado/disconnected.
        """
        while True:
            time.sleep(5)
            now = datetime.utcnow()
            to_save = {}
            for uid, info in self.peers.items():
                ip = info['ip']
                if ip in self.local_ips:
                    continue
                age = (now - info['last_seen']).total_seconds()
                status = 'connected' if age < OFFLINE_THRESHOLD else 'disconnected'
                to_save[uid] = {
                    'ip': ip,
                    'last_seen': info['last_seen'],
                    'status': status
                }
            self.peers_store.save(to_save)

    def handle_echo(self, data: bytes, addr):
        """
        Procesa un Echo-Request (op_code=0):
        - Ignora si la IP es local o el UID es el propio.
        - Responde Echo-Reply.
        - Registra o actualiza el peer, eliminando antiguos UID de la misma IP.
        """
        hdr = unpack_header(data[:HEADER_SIZE])
        raw_peer = hdr['user_from'].rstrip(b'\x00')
        peer_ip = addr[0]

        if peer_ip in self.local_ips or raw_peer == self.raw_id:
            return

        # Responder
        self.sock.sendto(pack_response(0, self.user_id), addr)

        # Eliminar UID previos para esta IP
        for uid in list(self.peers):
            if self.peers[uid]['ip'] == peer_ip and uid != raw_peer:
                del self.peers[uid]

        # Registrar/actualizar
        self.peers[raw_peer] = {
            'ip': peer_ip,
            'last_seen': datetime.utcnow()
        }

    def handle_response(self, data: bytes, addr):
        """
        Procesa un Echo-Reply (RESPONSE_FMT):
        - Igual que handle_echo, pero desempaquetando RESPONSE_FMT.
        """
        resp = unpack_response(data[:RESPONSE_SIZE])
        raw_peer = resp['responder'].rstrip(b'\x00')
        peer_ip = addr[0]

        if resp['status'] != 0 or peer_ip in self.local_ips or raw_peer == self.raw_id:
            return

        for uid in list(self.peers):
            if self.peers[uid]['ip'] == peer_ip and uid != raw_peer:
                del self.peers[uid]

        self.peers[raw_peer] = {
            'ip': peer_ip,
            'last_seen': datetime.utcnow()
        }

    def get_peers(self) -> dict:
        """
        Devuelve solo peers cuya IP no sea local,
        con su last_seen actualizado.
        """
        return {
            uid: info
            for uid, info in self.peers.items()
            if info['ip'] not in self.local_ips
        }
