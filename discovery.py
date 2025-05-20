import socket
import threading
import time
from util import get_local_ip
from protocol import pack_header, unpack_header, pack_response, unpack_response

LCP_PORT      = 9990
BROADCAST_UID = '\xff' * 20
BROADCAST_INTERVAL = 5.0  # segundos

class Discovery:
    def __init__(self, user_id: str, timeout: float = 2.0):
        self.user_id = user_id
        self.timeout = timeout
        self.peers   = {}

        # Calcula broadcast de la subred /24 a partir de tu IP local
        local_ip = get_local_ip()
        octs = local_ip.split('.')
        self.broadcast_ip = '.'.join(octs[:3] + ['255'])
        print(f"[Discovery] IP local: {local_ip}, broadcast: {self.broadcast_ip}")

        # Socket para recibir respuestas en todas las interfaces
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', LCP_PORT))
        self.sock.settimeout(1.0)

        # Arranca hilos
        threading.Thread(target=self._listen_responses, daemon=True).start()
        threading.Thread(target=self._broadcast_loop, daemon=True).start()

    def _listen_responses(self):
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
            print(f"[Discovery] Recibido paquete de {addr}: op={hdr['op_code']} from={hdr['user_from']}")
            if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                # responder eco
                try:
                    self.sock.sendto(pack_response(0, self.user_id), addr)
                    print(f"[Discovery] Respondí eco a {addr}")
                except Exception as e:
                    print(f"[Discovery] Error al responder eco: {e}")

    def _broadcast_loop(self):
        print("[Discovery] Hilo de broadcast periódico iniciado")
        while True:
            try:
                send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                send_sock.bind(('', 0))
                pkt = pack_header(self.user_id, BROADCAST_UID, 0)
                send_sock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
                print(f"[Discovery] Enviado broadcast a {self.broadcast_ip}:{LCP_PORT}")
                send_sock.close()
            except Exception as e:
                print(f"[Discovery] Error en broadcast: {e}")
            time.sleep(BROADCAST_INTERVAL)

    def discover(self) -> dict[str, str]:
        """Recolecta respuestas puntuales en timeout segundos."""
        found = {}
        self.sock.settimeout(self.timeout)
        start = time.time()
        while time.time() - start < self.timeout:
            try:
                data, addr = self.sock.recvfrom(1024)
            except socket.timeout:
                break
            hdr = unpack_header(data)
            print(f"[Discovery] discover() got {hdr['user_from']} from {addr}")
            if hdr['op_code'] == 0 and hdr['user_from'] != self.user_id:
                found[hdr['user_from']] = addr[0]
        self.peers = found
        print(f"[Discovery] peers descubiertos: {found}")
        return found

    def stop(self):
        self.sock.close()
