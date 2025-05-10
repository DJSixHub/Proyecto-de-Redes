import socket
import threading
import os

from constants import BIND_ADDR, UDP_PORT, TCP_PORT, HEADER_SIZE
from packet import encode_header, decode_header
from neighbor_table import NeighborTable

class FileTransfer:
    def __init__(self, self_id: str, neighbors: NeighborTable, receive_dir: str = '.'):
        self.self_id = self_id
        self.neighbors = neighbors
        self.receive_dir = receive_dir
        os.makedirs(self.receive_dir, exist_ok=True)

        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self.udp_sock.bind((BIND_ADDR, UDP_PORT))
        except PermissionError:
            self._bind_in_range(self.udp_sock, BIND_ADDR, 10000, 11000)

        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.tcp_sock.bind((BIND_ADDR, TCP_PORT))
        except PermissionError:
            self._bind_in_range(self.tcp_sock, BIND_ADDR, 11000, 12000)
        self.tcp_sock.listen(5)

        threading.Thread(target=self._udp_listener, daemon=True).start()
        threading.Thread(target=self._tcp_listener, daemon=True).start()

    def send_file(self, filepath: str):
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        meta = f"{filename}:{filesize}".encode('utf-8')
        header = encode_header(
            user_id_from=self.self_id,
            user_id_to='broadcast',
            opcode=2,
            body_id=0,
            body_length=len(meta)
        )
        packet = header + meta
        self.udp_sock.sendto(packet, ('<broadcast>', UDP_PORT))
        def serve():
            while True:
                conn, _ = self.tcp_sock.accept()
                threading.Thread(target=self._send_over_tcp, args=(conn, filepath), daemon=True).start()
        threading.Thread(target=serve, daemon=True).start()

    def _udp_listener(self):
        while True:
            data, addr = self.udp_sock.recvfrom(4096)
            try:
                hdr = decode_header(data[:HEADER_SIZE])
            except ValueError:
                continue
            if hdr['opcode'] != 2 or hdr['user_id_from'] == self.self_id:
                continue
            body = data[HEADER_SIZE:HEADER_SIZE+hdr['body_length']].decode('utf-8')
            filename, filesize = body.split(':', 1)
            if hdr['body_id'] == 0:
                reply = encode_header(
                    user_id_from=self.self_id,
                    user_id_to=hdr['user_id_from'],
                    opcode=2,
                    body_id=1,
                    body_length=0
                )
                self.udp_sock.sendto(reply, (addr[0], UDP_PORT))

    def _tcp_listener(self):
        while True:
            conn, _ = self.tcp_sock.accept()
            threading.Thread(target=self._receive_over_tcp, args=(conn,), daemon=True).start()

    def _receive_over_tcp(self, conn: socket.socket):
        header = conn.recv(1024).decode('utf-8')
        filename, filesize = header.split(':', 1)
        filesize = int(filesize)
        path = os.path.join(self.receive_dir, filename)
        with open(path, 'wb') as f:
            received = 0
            while received < filesize:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                f.write(chunk)
                received += len(chunk)
        conn.close()

    def _send_over_tcp(self, conn: socket.socket, filepath: str):
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        meta = f"{filename}:{filesize}".encode('utf-8')
        conn.sendall(meta)
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                conn.sendall(chunk)
        conn.close()

    def _bind_in_range(self, sock: socket.socket, addr: str, start_port: int, end_port: int) -> int:
        for p in range(start_port, end_port):
            try:
                sock.bind((addr, p))
                return p
            except PermissionError:
                continue
        raise RuntimeError(f"No se pudo bindear en ningún puerto de {start_port}-{end_port}")
