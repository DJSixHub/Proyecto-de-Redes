import socket
import threading
from pathlib import Path
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
            except Exception:
                continue
            hdr = unpack_header(data)
            if hdr['op_code'] == 1:
                try:
                    self.udp_sock.sendto(pack_response(0, self.user_id), addr)
                except:
                    pass
            elif hdr['op_code'] == 2:
                msg = data[HEADER_SIZE:].decode(errors='ignore')
                self.on_message(hdr['user_from'], msg)

    def _serve_tcp(self):
        while True:
            try:
                conn, addr = self.tcp_sock.accept()
                threading.Thread(target=self._handle_tcp, args=(conn,), daemon=True).start()
            except Exception:
                continue

    def _handle_tcp(self, conn):
        try:
            header = conn.recv(HEADER_SIZE)
            hdr = unpack_header(header)
            filename = hdr['user_to']  # archivo enviado codificado aquí
            path = Path("Descargas") / filename
            with open(path, "wb") as f:
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    f.write(data)
            self.on_file(hdr['user_from'], str(path))
        except Exception as e:
            print(f"[Messaging] Error recibiendo archivo: {e}")
        finally:
            conn.close()

    def send_message(self, uid: str, msg: str):
        try:
            ip = self._get_peer_ip(uid)
            hdr = pack_header(self.user_id, uid, 2, 0, len(msg.encode()))
            self.udp_sock.sendto(hdr + msg.encode(), (ip, LCP_PORT))
        except Exception as e:
            print(f"[Messaging] Error enviando mensaje a {uid}: {e}")

    def send_file(self, uid: str, filepath: str):
        try:
            ip = self._get_peer_ip(uid)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, LCP_PORT))
            filename = Path(filepath).name
            hdr = pack_header(self.user_id, filename, 3)
            sock.sendall(hdr)
            with open(filepath, "rb") as f:
                while chunk := f.read(1024):
                    sock.sendall(chunk)
            sock.close()
        except Exception as e:
            print(f"[Messaging] Error enviando archivo a {uid}: {e}")

    def _get_peer_ip(self, uid: str) -> str:
        # Esta función debe coordinar con Discovery
        # Como alternativa temporal, puedes pasar IP directamente si no tienes tabla
        for k, v in self.on_message.__self__.peers.items():
            if k == uid:
                return v
        raise ValueError(f"No se encontró IP para {uid}")
