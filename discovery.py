import socket
import threading
import time
from protocol import (
    pack_header, unpack_response,
    HEADER_SIZE, RESPONSE_SIZE, BROADCAST_UID,
    pack_response
)

LCP_PORT = 9990
DISCOVERY_RETRIES = 2
BROADCAST_INTERVAL = 10  # seconds

class Discovery:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', LCP_PORT))
        self.sock.settimeout(1.0)

        self.broadcast_ip = self._find_broadcast()
        self.peers = {}

        threading.Thread(target=self._listener_loop, daemon=True).start()
        threading.Thread(target=self._broadcast_loop, daemon=True).start()

    def _find_broadcast(self) -> str:
        from util import get_local_ip_and_broadcast
        _, broadcast = get_local_ip_and_broadcast()
        return broadcast

    def _listener_loop(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)

                if len(data) == HEADER_SIZE:
                    header = self._parse_echo_header(data)
                    if header:
                        sender = header["user_from"]
                        target = header["user_to"]
                        op = header["op_code"]

                        if target == BROADCAST_UID.decode('latin1') and op == 0:
                            print(f"[Discovery] Echo recibido de {sender} @ {addr[0]}")
                            response = pack_response(0, self.user_id)
                            self.sock.sendto(response, addr)
                    continue

                elif len(data) == RESPONSE_SIZE:
                    status, responder = unpack_response(data)
                    if status == 0 and responder != self.user_id:
                        self.peers[responder] = addr[0]
                        print(f"[Discovery] Echo-Reply de {responder} @ {addr[0]}")

                else:
                    print(f"[Discovery] Paquete ignorado, tamaño inesperado: {len(data)}")

            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] Error en listener: {e}")

    def _broadcast_loop(self):
        pkt = pack_header(self.user_id, BROADCAST_UID.decode('latin1'), 0)
        while True:
            try:
                print("[Discovery] Enviando broadcast Echo...")
                self.sock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
            except Exception as e:
                print(f"[Discovery] Error al enviar broadcast: {e}")
            time.sleep(BROADCAST_INTERVAL)

    def search_peers(self, duration=2.0) -> dict:
        """Descubrimiento puntual (por botón). Devuelve {user_id: ip}"""
        pkt = pack_header(self.user_id, BROADCAST_UID.decode('latin1'), 0)
        end_time = time.time() + duration

        found = {}

        for _ in range(DISCOVERY_RETRIES):
            try:
                print("[Discovery] → Broadcast puntual de descubrimiento")
                self.sock.sendto(pkt, (self.broadcast_ip, LCP_PORT))
            except Exception as e:
                print(f"[Discovery] Error en broadcast puntual: {e}")
            time.sleep(0.5)

        while time.time() < end_time:
            try:
                data, addr = self.sock.recvfrom(1024)
                if len(data) == RESPONSE_SIZE:
                    status, responder = unpack_response(data)
                    if status == 0 and responder != self.user_id:
                        found[responder] = addr[0]
                        print(f"[Discovery] ← Respuesta puntual de {responder}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] Error recibiendo respuesta: {e}")

        return found

    def _parse_echo_header(self, data: bytes):
        from protocol import unpack_header
        try:
            header = unpack_header(data)
            return header
        except Exception as e:
            print(f"[Discovery] Header inválido: {e}")
            return None
