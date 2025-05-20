import socket
import threading
import time
from util import get_local_ip
from protocol import pack_header, unpack_header, pack_response

LCP_PORT           = 9990
BROADCAST_UID      = '\xff' * 20
BROADCAST_INTERVAL = 5.0  # segundos entre broadcasts periódicos

class Discovery:
    def __init__(self, user_id: str, timeout: float = 2.0):
        self.user_id = user_id
        self.timeout = timeout
        self.peers   = {}  # mapa user_id -> ip

        # Calcula la dirección de broadcast /24 a partir de tu IP
        local_ip = get_local_ip()
        octs = local_ip.split('.')
        self.broadcast_ip = '.'.join(octs[:3] + ['255'])
        print(f"[Discovery] IP local: {local_ip}, broadcast: {self.broadcast_ip}")

        # Socket para recibir y responder ecos
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', LCP_PORT))
        self.sock.settimeout(1.0)

        # Inicia hilos
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
            # Si es Echo request para broadcast
            if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                peer_id = hdr['user_from']
                peer_ip = addr[0]
                # Guarda o actualiza el peer
                self.peers[peer_id] = peer_ip
                # Responde el eco
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

    def discover(self) -> dict[str, str]:
        """
        Para llamadas manuales: devuelve el diccionario actual de peers.
        """
        return self.peers

    def stop(self):
        """Detiene los hilos y cierra el socket."""
        self.sock.close()
