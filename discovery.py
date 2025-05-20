import socket
import threading
import time
from util import get_local_ip_and_broadcast
from protocol import pack_header, unpack_header, pack_response, unpack_response

LCP_PORT           = 9990
BROADCAST_UID      = '\xff' * 20
BROADCAST_INTERVAL = 5.0  # segundos

class Discovery:
    def __init__(self, user_id: str, timeout: float = 2.0):
        local_ip, broadcast_ip = get_local_ip_and_broadcast()
        self.broadcast_ip = broadcast_ip
        self.user_id = user_id
        self.timeout = timeout
        self.peers = {}

        print(f"[Discovery] IP local: {local_ip}, broadcast: {self.broadcast_ip}")

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
                header = unpack_header(data)
                if header['user_from'] == self.user_id:
                    continue
                if header['user_from'] not in self.peers:
                    print(f"[Discovery] Nuevo peer: {header['user_from']} desde {addr[0]}")
                self.peers[header['user_from']] = addr[0]
                reply = pack_response(1, self.user_id)
                self.sock.sendto(reply, addr)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] Error en listener: {e}")

    def _broadcast_loop(self):
        while True:
            try:
                pkt = pack_header(self.user_id, '', 0)
                self.sock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
                time.sleep(BROADCAST_INTERVAL)
            except Exception as e:
                print(f"[Discovery] Error al hacer broadcast: {e}")

    def search_peers(self, duration=2.0):
        self.peers.clear()
        pkt = pack_header(self.user_id, '', 0)
        self.sock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
        start = time.time()
        while time.time() - start < duration:
            try:
                data, addr = self.sock.recvfrom(1024)
                status, responder_uid = unpack_response(data)
                if responder_uid != self.user_id:
                    self.peers[responder_uid] = addr[0]
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] Error buscando peers: {e}")
        return self.peers
