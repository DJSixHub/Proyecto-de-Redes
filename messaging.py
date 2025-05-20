import socket
import threading
from pathlib import Path
from protocol import (
    pack_header, unpack_header,
    HEADER_SIZE
)

LCP_PORT = 9990

class Messaging:
    def __init__(self, user_id: str, on_message, on_file, udp_sock=None):
        self.user_id = user_id
        self.on_message = on_message
        self.on_file = on_file
        self._peer_map = {}  # nickname -> IP

        if udp_sock:
            self.udp_sock = udp_sock
        else:
            self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp_sock.bind(('', LCP_PORT))

        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind(('', LCP_PORT))
        self.tcp_sock.listen(5)

        threading.Thread(target=self._serve_udp, daemon=True).start()
        threading.Thread(target=self._serve_tcp, daemon=True).start()

    def update_peers(self, peer_dict):
        self._peer_map = peer_dict

    def _get_peer_ip(self, nickname: str) -> str:
        if nickname in self._peer_map:
            return self._peer_map[nickname]
        raise ValueError(f"No se encontró IP para {nickname}")

    def _serve_udp(self):
        while True:
            try:
                data, addr = self.udp_sock.recvfrom(HEADER_SIZE + 4096)
                if len(data) < HEADER_SIZE:
                    continue

                header = unpack_header(data)
                if header['op_code'] != 1:
                    continue

                body = data[HEADER_SIZE:HEADER_SIZE + header['body_len']]
                text = body.decode(errors='ignore')
                self.on_message(header['user_from'], text)

            except Exception as e:
                print(f"[Messaging] Error UDP: {e}")

    def send_message(self, nickname: str, text: str):
        try:
            ip = self._get_peer_ip(nickname)
            msg_bytes = text.encode()
            hdr = pack_header(self.user_id, nickname, 1, 0, len(msg_bytes))  # op_code = 1
            self.udp_sock.sendto(hdr + msg_bytes, (ip, LCP_PORT))
        except Exception as e:
            print(f"[Messaging] Error enviando mensaje a {nickname}: {e}")

    def _serve_tcp(self):
        while True:
            try:
                conn, _ = self.tcp_sock.accept()
                threading.Thread(target=self._handle_tcp, args=(conn,), daemon=True).start()
            except Exception as e:
                print(f"[Messaging] Error TCP: {e}")

    def _handle_tcp(self, conn):
        try:
            header = conn.recv(HEADER_SIZE)
            if len(header) < HEADER_SIZE:
                return

            hdr = unpack_header(header)
            if hdr['op_code'] != 2:
                return

            filename = hdr['user_to']
            sender = hdr['user_from']

            path = Path("Descargas") / filename
            with open(path, "wb") as f:
                while chunk := conn.recv(1024):
                    f.write(chunk)

            self.on_file(sender, str(path))

        except Exception as e:
            print(f"[Messaging] Error recibiendo archivo: {e}")
        finally:
            conn.close()

    def send_file(self, nickname: str, filepath: str):
        try:
            ip = self._get_peer_ip(nickname)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, LCP_PORT))

            filename = Path(filepath).name
            hdr = pack_header(self.user_id, filename, 2)  # op_code = 2
            sock.sendall(hdr)
            with open(filepath, "rb") as f:
                while chunk := f.read(1024):
                    sock.sendall(chunk)
            sock.close()

        except Exception as e:
            print(f"[Messaging] Error enviando archivo a {nickname}: {e}")
