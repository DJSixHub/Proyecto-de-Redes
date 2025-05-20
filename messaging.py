import socket
import threading
from pathlib import Path
from protocol import (
    pack_header, unpack_header,
    pack_response, unpack_response,
    HEADER_SIZE
)

LCP_PORT = 9990

class Messaging:
    def __init__(self, user_id: str, on_message, on_file, udp_sock=None):
        self.user_id = user_id
        self.on_message = on_message
        self.on_file = on_file
        self._peer_map = {}  # peer_mac -> {'nick': ..., 'ip': ...}

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

    def _get_peer_ip(self, peer_mac: str) -> str:
        if peer_mac in self._peer_map:
            return self._peer_map[peer_mac]['ip']
        raise ValueError(f"No se encontró IP para {peer_mac}")

    def _get_peer_nick(self, peer_mac: str) -> str:
        if peer_mac in self._peer_map:
            return self._peer_map[peer_mac]['nick']
        return peer_mac

    def _serve_udp(self):
        while True:
            try:
                data, addr = self.udp_sock.recvfrom(HEADER_SIZE + 4096)
                if len(data) < HEADER_SIZE:
                    continue

                header = unpack_header(data)
                if header['op_code'] != 2:
                    continue

                total_len = header['body_len']
                payload = data[HEADER_SIZE:]

                if len(payload) < total_len:
                    # truncado
                    print("[Messaging] Mensaje truncado, ignorado.")
                    continue

                sender = header['user_from']
                sender_nick, sender_mac = sender.split('|') if '|' in sender else (sender, sender)

                text = payload[:total_len].decode(errors='ignore')

                self.on_message(sender_mac, text)

            except Exception as e:
                print(f"[Messaging] Error UDP: {e}")

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
            if len(header) < HEADER_SIZE:
                return
            hdr = unpack_header(header)

            sender = hdr['user_from']
            sender_nick, sender_mac = sender.split('|') if '|' in sender else (sender, sender)
            filename = hdr['user_to']  # usamos 'user_to' para pasar nombre del archivo

            path = Path("Descargas") / filename
            with open(path, "wb") as f:
                while True:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    f.write(chunk)

            self.on_file(sender_mac, str(path))

        except Exception as e:
            print(f"[Messaging] Error archivo: {e}")
        finally:
            conn.close()

    def send_message(self, peer_mac: str, msg: str):
        try:
            ip = self._get_peer_ip(peer_mac)
            nick = self._peer_map[peer_mac]['nick']
            full_id = f"{nick}|{peer_mac}"

            hdr = pack_header(self.user_id, '', 2, 0, len(msg.encode()))
            packet = hdr + msg.encode()
            self.udp_sock.sendto(packet, (ip, LCP_PORT))
        except Exception as e:
            print(f"[Messaging] Error enviando mensaje a {peer_mac}: {e}")

    def send_file(self, peer_mac: str, filepath: str):
        try:
            ip = self._get_peer_ip(peer_mac)
            nick = self._peer_map[peer_mac]['nick']
            full_id = f"{nick}|{peer_mac}"

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
            print(f"[Messaging] Error enviando archivo a {peer_mac}: {e}")
