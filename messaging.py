import socket
import threading
import queue
import struct

from constants import BIND_ADDR, UDP_PORT, HEADER_SIZE, BODYLEN_SIZE
from packet import encode_header, decode_header
from neighbor_table import NeighborTable

class Messaging:
    def __init__(self, self_id: str, neighbors: NeighborTable, on_message=None):
        self.self_id = self_id
        self.neighbors = neighbors
        self.on_message = on_message or (lambda text, frm: print(f"[{frm}] {text}"))
        self._msg_queue = queue.Queue()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        try:
            self.sock.bind((BIND_ADDR, UDP_PORT))
        except PermissionError:
            new_port = self._bind_in_range(self.sock, BIND_ADDR, 10000, 11000)

        threading.Thread(target=self._listener, daemon=True).start()
        threading.Thread(target=self._processor, daemon=True).start()

    def send_message(self, text: str):
        body = text.encode("utf-8")
        header = encode_header(
            user_id_from=self.self_id,
            user_id_to="broadcast",
            opcode=1,
            body_id=0,
            body_length=len(body)
        )
        packet = header + struct.pack("!Q", 0) + body
        self.sock.sendto(packet, ('<broadcast>', UDP_PORT))

    def _listener(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError:
                continue

            try:
                hdr = decode_header(data[:HEADER_SIZE])
            except ValueError:
                continue

            if hdr["opcode"] != 1 or hdr["user_id_from"] == self.self_id:
                continue

            blen = hdr["body_length"]
            offset = HEADER_SIZE + BODYLEN_SIZE
            text = data[offset: offset + blen].decode("utf-8", errors="ignore")
            self._msg_queue.put((hdr["user_id_from"], text))

    def _processor(self):
        while True:
            frm, text = self._msg_queue.get()
            try:
                self.on_message(text, frm)
            finally:
                self._msg_queue.task_done()

    def _bind_in_range(self, sock: socket.socket, addr: str, start_port: int, end_port: int) -> int:
        for p in range(start_port, end_port):
            try:
                sock.bind((addr, p))
                return p
            except PermissionError:
                continue
        raise RuntimeError(f"No se pudo bindear en ningún puerto de {start_port}-{end_port}")
