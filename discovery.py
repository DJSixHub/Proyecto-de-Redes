import socket
import threading
import time
from util import get_local_ip
from protocol import (
    pack_header, unpack_header,
    pack_response, unpack_response
)

LCP_PORT      = 9990
BROADCAST_IP  = '255.255.255.255'
BROADCAST_UID = '\xff' * 20
BROADCAST_INTERVAL = 3.0  # segundos entre broadcasts periódicos

class Discovery:
    def __init__(self, user_id: str, timeout: float = 2.0):
        self.user_id = user_id
        self.timeout = timeout
        self.peers = {}
        # Socket para recibir respuestas (ligado a todas interfaces)
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('', LCP_PORT))
        except Exception as e:
            print(f"[Discovery] Error al bind UDP (¿firewall?): {e}")
            raise

        # Hilo de escucha de respuestas
        self._stop_event = threading.Event()
        threading.Thread(target=self._listen_responses, daemon=True).start()
        # Hilo de broadcast periódico
        threading.Thread(target=self._broadcast_loop, daemon=True).start()

    def _listen_responses(self):
        while not self._stop_event.is_set():
            try:
                data, addr = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] Error recvfrom: {e}")
                continue

            hdr = unpack_header(data)
            if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                # Responde al eco
                try:
                    self.sock.sendto(pack_response(0, self.user_id), addr)
                except Exception as e:
                    print(f"[Discovery] No pude responder eco (¿firewall?): {e}")

    def _broadcast_loop(self):
        while not self._stop_event.is_set():
            try:
                send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                send_sock.bind(('', 0))
                pkt = pack_header(self.user_id, BROADCAST_UID, 0)
                send_sock.sendto(pkt, (BROADCAST_IP, LCP_PORT))
                send_sock.close()
            except Exception as e:
                print(f"[Discovery] Error enviando broadcast (¿firewall?): {e}")
            time.sleep(BROADCAST_INTERVAL)

    def discover(self) -> dict[str, str]:
        
        found = {}
        self.sock.settimeout(self.timeout)
        start = time.time()
        while time.time() - start < self.timeout:
            try:
                data, addr = self.sock.recvfrom(1024)
            except socket.timeout:
                break
            except Exception as e:
                print(f"[Discovery] Error recvfrom en discover: {e}")
                break
            status, rid = unpack_response(data)
            if status == 0 and rid != self.user_id:
                found[rid] = addr[0]
        self.peers = found
        return found

    def stop(self):
        """Detiene los hilos de broadcast y escucha."""
        self._stop_event.set()
        self.sock.close()
