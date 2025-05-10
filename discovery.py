
import socket
import threading
import time

from constants import UDP_PORT, TIMEOUT_SECONDS
from packet import encode_header, decode_header
from neighbor_table import NeighborTable


class Discovery:
    def __init__(self, self_id: str, neighbor_table: NeighborTable):
        self.self_id = self_id
        self.table = neighbor_table

        # Socket UDP para broadcast y recepción
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("", UDP_PORT))

        # Hilo de escucha
        self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listen_thread.start()

    def send_discovery(self):
        
        pkt = encode_header(
            user_id_from=self.self_id,
            user_id_to="broadcast",
            opcode=0,        
            body_id=0,
            body_length=0
        )
        # Broadcast al puerto UDP
        self.sock.sendto(pkt, ("<broadcast>", UDP_PORT))

    def _listen_loop(self):
        
        while True:
            data, addr = self.sock.recvfrom(4096)
            try:
                hdr = decode_header(data[:100])
            except Exception:
                continue

            # Ignorar propios 
            if hdr["user_id_from"] == self.self_id:
                continue

            # Echo request
            if hdr["opcode"] == 0 and hdr["body_id"] == 0:
                reply = encode_header(
                    user_id_from=self.self_id,
                    user_id_to=hdr["user_id_from"],
                    opcode=0,
                    body_id=1,
                    body_length=0
                )
                self.sock.sendto(reply, (addr[0], UDP_PORT))

            # Echo reply
            elif hdr["opcode"] == 0 and hdr["body_id"] == 1:
                self.table.add_neighbor(hdr["user_id_from"], addr[0])

def start_autodiscovery(self_id: str, table: NeighborTable):
    disc = Discovery(self_id, table)
    disc.send_discovery()
    def periodic():
        while True:
            time.sleep(TIMEOUT_SECONDS)
            disc.send_discovery()
    threading.Thread(target=periodic, daemon=True).start()
