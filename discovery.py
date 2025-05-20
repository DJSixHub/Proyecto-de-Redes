import socket
import threading
import time
from util import get_local_ip
from protocol import pack_header, unpack_header, pack_response, unpack_response

LCP_PORT      = 9990
BROADCAST_IP  = '255.255.255.255'
BROADCAST_UID = '\xff' * 20

class Discovery:
    def __init__(self, user_id: str, timeout: float = 2.0):
        self.user_id = user_id
        self.timeout = timeout
        # Socket para recibir respuestas, ligado a todas las interfaces
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', LCP_PORT))

    def start_listener(self):
        threading.Thread(target=self._listen_responses, daemon=True).start()

    def _listen_responses(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
            except OSError:
                continue
            hdr = unpack_header(data)
            if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                # responde al originador del echo
                self.sock.sendto(pack_response(0, self.user_id), addr)

    def discover(self) -> dict[str, str]:
        # Socket efímero para enviar el broadcast
        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        send_sock.bind(('', 0))
        pkt = pack_header(self.user_id, BROADCAST_UID, 0)
        send_sock.sendto(pkt, (BROADCAST_IP, LCP_PORT))
        send_sock.close()

        peers: dict[str, str] = {}
        self.sock.settimeout(self.timeout)
        start = time.time()
        while time.time() - start < self.timeout:
            try:
                data, addr = self.sock.recvfrom(1024)
            except socket.timeout:
                break
            status, rid = unpack_response(data)
            if status == 0 and rid != self.user_id:
                peers[rid] = addr[0]
        return peers
