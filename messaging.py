# messaging.py
import socket
import threading
from util import get_local_ip
from protocol import (
    pack_header, unpack_header,
    pack_response, unpack_response,
    HEADER_SIZE, RESPONSE_SIZE
)

LCP_PORT = 9990

class Messaging:
    def __init__(self, user_id: str, on_message, on_file, udp_sock=None):
        self.user_id    = user_id
        self.on_message = on_message
        self.on_file    = on_file

        # Reutiliza socket UDP de Discovery o crea uno nuevo
        if udp_sock:
            self.udp_sock = udp_sock
        else:
            self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            local_ip = get_local_ip()
            self.udp_sock.bind((local_ip, LCP_PORT))

        # Socket TCP para archivos, ligado solo a IP local
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        local_ip = get_local_ip()
        self.tcp_sock.bind((local_ip, LCP_PORT))
        self.tcp_sock.listen(5)

        threading.Thread(target=self._serve_udp, daemon=True).start()
        threading.Thread(target=self._serve_tcp, daemon=True).start()

    # Atiende headers y cuerpos de mensajes UDP y dispara callback
    def _serve_udp(self):
        while True:
            data, addr = self.udp_sock.recvfrom(HEADER_SIZE + 1024)
            hdr = unpack_header(data)
            if hdr['op_code'] == 1:
                self.udp_sock.sendto(pack_response(0, self.user_id), addr)
                body, _ = self.udp_sock.recvfrom(hdr['body_len'] + 8)
                self.on_message(hdr['user_from'], body[8:].decode())

    # Envía mensaje de texto en dos fases (header + cuerpo)
    def send_message(self, target_ip: str, target_id: str, text: str):
        body = text.encode()
        hdr  = pack_header(self.user_id, target_id, 1, 1, len(body))
        self.udp_sock.sendto(hdr, (target_ip, LCP_PORT))
        status, _ = unpack_response(self.udp_sock.recv(RESPONSE_SIZE))
        if status != 0:
            raise RuntimeError("Handshake de mensaje fallido")
        self.udp_sock.sendto((1).to_bytes(8, 'big') + body,
                             (target_ip, LCP_PORT))

    # Atiende conexiones TCP entrantes para recepción de archivos
    def _serve_tcp(self):
        while True:
            conn, _ = self.tcp_sock.accept()
            header = conn.recv(8)
            content = b''
            while chunk := conn.recv(4096):
                content += chunk
            conn.sendall(pack_response(0, self.user_id))
            self.on_file(None, content)

    # Envía un archivo: handshake UDP + payload TCP
    def send_file(self, target_ip: str, target_id: str, filepath: str):
        data = open(filepath, 'rb').read()
        hdr  = pack_header(self.user_id, target_id, 2, 1, len(data))
        self.udp_sock.sendto(hdr, (target_ip, LCP_PORT))
        status, _ = unpack_response(self.udp_sock.recv(RESPONSE_SIZE))
        if status != 0:
            raise RuntimeError("Handshake de archivo fallido")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((target_ip, LCP_PORT))
        s.sendall((1).to_bytes(8, 'big') + data)
        status, _ = unpack_response(s.recv(RESPONSE_SIZE))
        s.close()
        if status != 0:
            raise RuntimeError("Transferencia de archivo fallida")

    # Envía mensaje a múltiples targets con sufijo de grupo
    def send_group_message(self, targets: dict[str, str], text: str):
        sufijo = f" (también se le envió a: {', '.join(targets.keys())})"
        msg = text + sufijo
        for uid, ip in targets.items():
            try:
                self.send_message(ip, uid, msg)
            except Exception as e:
                print(f"Error enviando a {uid}@{ip}: {e}")
