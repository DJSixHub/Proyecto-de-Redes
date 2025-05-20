import socket
import threading
import time
from util import get_local_ip_and_broadcast
from protocol import (
    pack_header, unpack_header,
    pack_response, unpack_response,
    HEADER_SIZE, RESPONSE_SIZE, BROADCAST_UID
)

LCP_PORT = 9990
BROADCAST_INTERVAL = 5.0  # para emisión continua
DISCOVERY_RETRIES = 3     # veces que se reenvía en búsqueda

class Discovery:
    def __init__(self, user_id: str, timeout: float = 2.0):
        self.user_id = user_id
        self.timeout = timeout
        self.peers = {}  # nickname -> IP

        local_ip, broadcast_ip = get_local_ip_and_broadcast()
        self.local_ip = local_ip
        self.broadcast_ip = broadcast_ip

        print(f"[Discovery] IP local: {local_ip}, broadcast: {broadcast_ip}, usuario: {user_id}")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(('', LCP_PORT))
        self.sock.settimeout(1.0)

        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._broadcast_loop, daemon=True).start()

    def _listen_loop(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)

                if len(data) == HEADER_SIZE:
                    header = unpack_header(data)

                    if header['op_code'] != 0:
                        continue

                    sender = header['user_from']
                    if sender == self.user_id:
                        continue

                    # Agregar o actualizar peer
                    self.peers[sender] = addr[0]
                    print(f"[Discovery] Detectado: {sender} en {addr[0]}")

                    # Responder con paquete tipo Response
                    resp = pack_response(0, self.user_id)
                    self.sock.sendto(resp, addr)

                elif len(data) == RESPONSE_SIZE:
                    status, responder = unpack_response(data)
                    if responder != self.user_id:
                        self.peers[responder] = addr[0]

            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] Error en listener: {e}")

    def _broadcast_loop(self):
        pkt = pack_header(self.user_id, BROADCAST_UID.decode('latin1'), 0)
        while True:
            try:
                self.sock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
            except Exception as e:
                print(f"[Discovery] Error en broadcast: {e}")
            time.sleep(BROADCAST_INTERVAL)

    def search_peers(self, duration=2.0):
        pkt = pack_header(self.user_id, BROADCAST_UID.decode('latin1'), 0)
        end = time.time() + duration

        # Enviar múltiples paquetes
        for _ in range(DISCOVERY_RETRIES):
            try:
                self.sock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
            except Exception as e:
                print(f"[Discovery] Error al enviar broadcast: {e}")
            time.sleep(0.5)

        # Escuchar respuestas durante el resto del tiempo
        while time.time() < end:
            try:
                data, addr = self.sock.recvfrom(1024)
                if len(data) == RESPONSE_SIZE:
                    status, responder = unpack_response(data)
                    if responder != self.user_id:
                        self.peers[responder] = addr[0]
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] Error buscando peers: {e}")

        return self.peers
