import socket
import threading
import time
from util import get_local_ip
from protocol import pack_header, unpack_header, pack_response

LCP_PORT      = 9990
BROADCAST_UID = '\xff' * 20
BROADCAST_INTERVAL = 5.0  # segundos

class Discovery:
    def __init__(self, user_id: str, timeout: float = 2.0):
        self.user_id = user_id
        self.timeout = timeout
        self.peers = {}  # mapa user_id -> ip

        # Calcula broadcast /24
        local_ip = get_local_ip()
        octs = local_ip.split('.')
        self.broadcast_ip = '.'.join(octs[:3] + ['255'])
        print(f"[Discovery] IP local: {local_ip}, broadcast: {self.broadcast_ip}")

        # Socket para recibir y responder ecos
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', LCP_PORT))
        self.sock.settimeout(1.0)

        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._broadcast_loop, daemon=True).start()

    def _listen_loop(self):
        print("[Discovery] Hilo de escucha iniciado")
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] Error recvfrom: {e}")
                continue

            hdr = unpack_header(data)
            # si es echo request para broadcast UID, respondemos y guardamos peer
            if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                peer_id = hdr['user_from']
                peer_ip = addr[0]
                self.peers[peer_id] = peer_ip
                try:
                    self.sock.sendto(pack_response(0, self.user_id), addr)
                except Exception as e:
                    print(f"[Discovery] No pude responder eco: {e}")
                print(f"[Discovery] Descubierto peer {peer_id}@{peer_ip}")

    def _broadcast_loop(self):
        print("[Discovery] Hilo de broadcast periódico iniciado")
        while True:
            try:
                bsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                bsock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                pkt = pack_header(self.user_id, BROADCAST_UID, 0)
                bsock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
                bsock.close()
                print(f"[Discovery] Enviado broadcast a {self.broadcast_ip}:{LCP_PORT}")
            except Exception as e:
                print(f"[Discovery] Error broadcast: {e}")
            time.sleep(BROADCAST_INTERVAL)
