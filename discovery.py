import socket
import threading
import time
import uuid
from util import get_local_ip_and_broadcast
from protocol import pack_header, unpack_header, pack_response, unpack_response, HEADER_SIZE

LCP_PORT = 9990
BROADCAST_INTERVAL = 5.0  # segundos

class Discovery:
    def __init__(self, user_nick: str, timeout: float = 2.0):
        self.user_nick = user_nick
        self.timeout = timeout
        self.peers = {}  # key: MAC -> {'nick': ..., 'ip': ...}

        self.mac_addr = self._get_mac()
        local_ip, broadcast_ip = get_local_ip_and_broadcast()
        self.local_ip = local_ip
        self.broadcast_ip = broadcast_ip

        print(f"[Discovery] IP local: {local_ip}, broadcast: {broadcast_ip}, MAC: {self.mac_addr}")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(('', LCP_PORT))
        self.sock.settimeout(1.0)

        threading.Thread(target=self._listen_loop, daemon=True).start()
        threading.Thread(target=self._broadcast_loop, daemon=True).start()

    def _get_mac(self) -> str:
        return hex(uuid.getnode())[2:].upper()

    def _listen_loop(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
                if len(data) < HEADER_SIZE:
                    continue  # evitar error de desempaquetado

                header = unpack_header(data)

                sender_nick = header['user_from']
                sender_ip = addr[0]
                sender_mac = self._extract_mac(sender_nick)

                # no te agregues a ti mismo
                if sender_mac == self.mac_addr:
                    continue

                # actualiza o agrega peer
                self.peers[sender_mac] = {
                    'nick': self._strip_mac(sender_nick),
                    'ip': sender_ip
                }

                # respuesta tipo handshake
                reply = pack_response(1, self._build_nick_with_mac())
                self.sock.sendto(reply, addr)

            except Exception as e:
                print(f"[Discovery] Error en listener: {e}")

    def _broadcast_loop(self):
        while True:
            try:
                pkt = pack_header(
                    self._build_nick_with_mac(),
                    '',
                    op_code=0
                )
                self.sock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
                time.sleep(BROADCAST_INTERVAL)
            except Exception as e:
                print(f"[Discovery] Error al hacer broadcast: {e}")

    def search_peers(self, duration=2.0):
        self.peers.clear()
        pkt = pack_header(self._build_nick_with_mac(), '', op_code=0)
        self.sock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
        start = time.time()
        while time.time() - start < duration:
            try:
                data, addr = self.sock.recvfrom(1024)
                if len(data) < HEADER_SIZE:
                    continue
                status, responder = unpack_response(data)
                sender_mac = self._extract_mac(responder)
                if sender_mac != self.mac_addr:
                    self.peers[sender_mac] = {
                        'nick': self._strip_mac(responder),
                        'ip': addr[0]
                    }
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] Error buscando peers: {e}")
        return self.peers

    def _build_nick_with_mac(self) -> str:
        """Adjunta la MAC al nick visible para identificación persistente."""
        return f"{self.user_nick}|{self.mac_addr}"

    def _strip_mac(self, uid: str) -> str:
        return uid.split('|')[0] if '|' in uid else uid

    def _extract_mac(self, uid: str) -> str:
        return uid.split('|')[1] if '|' in uid else uid
