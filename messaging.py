import socket
import threading
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

        # Socket UDP para recibir mensajes (opcionalmente reutilizado)
        if udp_sock:
            self.udp_sock = udp_sock
        else:
            try:
                self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.udp_sock.bind(('', LCP_PORT))
            except Exception as e:
                print(f"[Messaging] Error bind UDP (¿firewall?): {e}")
                raise

        # Socket TCP para archivos
        try:
            self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_sock.bind(('', LCP_PORT))
            self.tcp_sock.listen(5)
        except Exception as e:
            print(f"[Messaging] Error bind TCP (¿firewall?): {e}")
            raise

        threading.Thread(target=self._serve_udp, daemon=True).start()
        threading.Thread(target=self._serve_tcp, daemon=True).start()

    def _serve_udp(self):
        while True:
            try:
                data, addr = self.udp_sock.recvfrom(HEADER_SIZE + 1024)
            except Exception as e:
                # ignora timeouts y otros errores menores
                continue

            hdr = unpack_header(data)
            if hdr['op_code'] == 1:
                try:
                    self.udp_sock.sendto(pack_response(0, self.user_id), addr)
                except Exception as e:
                    print(f"[Messaging] Error respondiendo handshake UDP: {e}")
                    continue
                try:
                    body, _ = self.udp_sock.recvfrom(hdr['body_len'] + 8)
                except Exception:
                    continue
                msg = body[8:].decode('utf-8', errors='ignore')
                self.on_message(hdr['user_from'], msg)

    def send_message(self, target_ip: str, target_id: str, text: str):
        body = text.encode()
        hdr  = pack_header(self.user_id, target_id, 1, 1, len(body))
        try:
            send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            send_sock.sendto(hdr, (target_ip, LCP_PORT))
            status, _ = unpack_response(send_sock.recv(RESPONSE_SIZE))
            if status != 0:
                raise RuntimeError("Handshake de mensaje fallido")
            send_sock.sendto((1).to_bytes(8, 'big') + body, (target_ip, LCP_PORT))
            send_sock.close()
        except Exception as e:
            print(f"[Messaging] Error enviando mensaje a {target_id}@{target_ip}: {e}")

    def _serve_tcp(self):
        while True:
            conn, _ = self.tcp_sock.accept()
            header = conn.recv(8)
            content = b''
            while chunk := conn.recv(4096):
                content += chunk
            try:
                conn.sendall(pack_response(0, self.user_id))
            except Exception as e:
                print(f"[Messaging] Error respondiendo TCP: {e}")
            self.on_file(None, content)

    def send_file(self, target_ip: str, target_id: str, filepath: str):
        try:
            data = Path(filepath).read_bytes()
            hdr  = pack_header(self.user_id, target_id, 2, 1, len(data))
            send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            send_sock.sendto(hdr, (target_ip, LCP_PORT))
            status, _ = unpack_response(send_sock.recv(RESPONSE_SIZE))
            if status != 0:
                raise RuntimeError("Handshake de archivo fallido")
            send_sock.close()

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((target_ip, LCP_PORT))
            s.sendall((1).to_bytes(8, 'big') + data)
            status, _ = unpack_response(s.recv(RESPONSE_SIZE))
            s.close()
            if status != 0:
                raise RuntimeError("Transferencia de archivo fallida")
        except Exception as e:
            print(f"[Messaging] Error enviando archivo a {target_id}@{target_ip}: {e}")

    def send_group_message(self, targets: dict[str, str], text: str):
        sufijo = f" (también se le envió a: {', '.join(targets.keys())})"
        full   = text + sufijo
        for uid, ip in targets.items():
            self.send_message(ip, uid, full)
