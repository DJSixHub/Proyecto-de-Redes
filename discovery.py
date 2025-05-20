import socket
import threading
import time
from util import get_local_ip
from protocol import pack_header, unpack_header, pack_response

LCP_PORT           = 9990
BROADCAST_UID      = '\xff' * 20
BROADCAST_INTERVAL = 5.0  # segundos

class Discovery:
    def __init__(self, user_id: str, timeout: float = 2.0):
        # calcula broadcast de la subred /24
        local_ip = get_local_ip()
        octs = local_ip.split('.')
        self.broadcast_ip = '.'.join(octs[:3] + ['255'])
        self.user_id = user_id
        self.timeout = timeout
        self.peers = {}
        # socket UDP para recibir ecos y enviar broadcasts
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(('', LCP_PORT))
        self.sock.settimeout(1.0)
        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._broadcast_loop, daemon=True).start()

    def _listen_loop(self):
        # recibe paquetes y responde ecos
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
        # envía broadcast periódico usando el mismo socket
        pkt = pack_header(self.user_id, BROADCAST_UID, 0)
        while True:
            try:
                self.sock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
            except:
                pass
            time.sleep(BROADCAST_INTERVAL)

    def discover(self) -> dict[str, str]:
        # devuelve el estado actual de peers
        return self.peers

    def stop(self):
        # cierra el socket de escucha
        self.sock.close()
