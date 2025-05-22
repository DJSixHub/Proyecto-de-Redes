# core/discovery.py

import socket
import threading
import time
from datetime import datetime

from core.protocol import (
    UDP_PORT,
    BROADCAST_UID,
    pack_header,
    unpack_header,
    pack_response,
    HEADER_SIZE
)


class Discovery:
    """
    Broadcast continuo y detección de peers sobre la interfaz Wi-Fi.
    - Se liga el socket sólo a la IP principal de la máquina (Wi-Fi).
    - Ignora el propio UID y la propia IP.
    - Evita duplicados basados en la misma IP.
    """

    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0,
                 peers_store=None):
        # UID raw y padding
        self.raw_id = user_id.rstrip(b'\x00')
        self.user_id = self.raw_id.ljust(20, b'\x00')

        self.broadcast_interval = broadcast_interval
        self.peers_store = peers_store

        # Determinar la IP de la interfaz principal (Wi-Fi)
        hostname = socket.gethostname()
        self.local_ip = socket.gethostbyname(hostname)
        # Para compatibilidad con clean(), exponemos local_ips como conjunto
        self.local_ips = {self.local_ip}

        # Mapa de peers: { uid_bytes: {'ip': str, 'last_seen': datetime} }
        self.peers = {}

        # Socket UDP ligado sólo a la IP Wi-Fi
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind((self.local_ip, UDP_PORT))

        # Hilos de fondo
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        threading.Thread(target=self._recv_loop, daemon=True).start()
        if self.peers_store:
            threading.Thread(target=self._persist_loop, daemon=True).start()

    def _broadcast_loop(self):
        """Envía un Echo-Request de broadcast cada intervalo."""
        while True:
            pkt = pack_header(
                user_from=self.user_id,
                user_to=BROADCAST_UID,
                op_code=0
            )
            self.sock.sendto(pkt, ('<broadcast>', UDP_PORT))
            time.sleep(self.broadcast_interval)

    def _recv_loop(self):
        """
        Bucle continuo de recepción:
         1) Recibe datagramas ≥ HEADER_SIZE
         2) Desempaqueta sólo op_code==0 (Echo-Request)
         3) Responde con Echo-Reply
         4) Añade peer si:
            - peer_id != self.raw_id
            - peer_ip not in self.local_ips
            - no existe otro peer con la misma IP
        """
        while True:
            data, addr = self.sock.recvfrom(4096)
            if len(data) < HEADER_SIZE:
                continue

            hdr = unpack_header(data[:HEADER_SIZE])
            if hdr['op_code'] != 0:
                continue

            # 1) responder Echo-Reply
            reply = pack_response(status=0, responder=self.user_id)
            self.sock.sendto(reply, addr)

            peer_id = hdr['user_from']
            peer_ip = addr[0]

            # 2) filtrar:
            if peer_id == self.raw_id:
                continue
            if peer_ip in self.local_ips:
                continue
            if any(info['ip'] == peer_ip for info in self.peers.values()):
                continue

            # 3) registrar
            self.peers[peer_id] = {
                'ip': peer_ip,
                'last_seen': datetime.utcnow()
            }

    def _persist_loop(self):
        """Vuelca self.peers a disco cada 5 s si existe peers_store."""
        while True:
            time.sleep(5)
            self.peers_store.save(self.peers)

    def get_peers(self) -> dict:
        """Devuelve una copia del diccionario actual de peers."""
        return self.peers.copy()
