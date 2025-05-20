import socket
import threading
import time
import ipaddress
from util import get_local_ip
from protocol import pack_header, unpack_header, pack_response

LCP_PORT = 9990
BROADCAST_UID = '\xff' * 20
BROADCAST_INTERVAL = 5.0  # segundos

class Discovery:
    def __init__(self, user_id: str, timeout: float = 2.0):
        # calcula broadcast de tu subred /24
        local_ip = get_local_ip()
        net = ipaddress.ip_network(f"{local_ip}/24", strict=False)
        self.broadcast_ip = str(net.broadcast_address)
        self.user_id = user_id
        self.timeout = timeout
        self.peers = {}
        # socket UDP para recibir y responder ecos
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', LCP_PORT))
        self.sock.settimeout(1.0)
        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._broadcast_loop, daemon=True).start()

    def _listen_loop(self):
        # recibe ecos y actualiza peers
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            hdr = unpack_header(data)
            if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                peer = hdr['user_from']
                self.peers[peer] = addr[0]
                try:
                    self.sock.sendto(pack_response(0, self.user_id), addr)
                except:
                    pass

    def _broadcast_loop(self):
        # envía broadcast periódico
        while True:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                pkt = pack_header(self.user_id, BROADCAST_UID, 0)
                s.sendto(pkt, (self.broadcast_ip, LCP_PORT))
                s.close()
            except:
                pass
            time.sleep(BROADCAST_INTERVAL)

    def discover(self) -> dict[str, str]:
        # devuelve el dict actual de peers
        return self.peers
