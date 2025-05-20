import socket
import threading
import random
import time
from pathlib import Path
from protocol import (
    pack_header, unpack_header,
    pack_response, unpack_response,
    HEADER_SIZE, RESPONSE_SIZE
)

LCP_PORT = 9990
DUPLICATE_EXPIRY = 30  # segundos

class Messaging:
    def __init__(self, user_id: str, on_message, on_file, udp_sock=None):
        self.user_id = user_id
        self.on_message = on_message
        self.on_file = on_file
        self._peer_map = {}  # user_id → ip
        self._pending_messages = {}  # body_id → metadata
        self._seen_messages = {}  # (user_from, body_id) → timestamp

        if udp_sock:
            self.udp_sock = udp_sock  # ← Socket ya creado por Discovery
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
        threading.Thread(target=self._cleanup_seen_messages, daemon=True).start()

    def update_peers(self, peer_dict):
        self._peer_map = peer_dict

    def _get_peer_ip(self, user_id: str) -> str:
        if user_id in self._peer_map:
            return self._peer_map[user_id]
        raise ValueError(f"No se encontró IP para {user_id}")

    def _serve_udp(self):
        while True:
            try:
                data, addr = self.udp_sock.recvfrom(HEADER_SIZE + 4096)

                if len(data) == HEADER_SIZE:
                    header = unpack_header(data)
                    op = header["op_code"]
                    body_id = header["body_id"]
                    sender = header["user_from"]

                    expected_ip = self._peer_map.get(sender)
                    if expected_ip and addr[0] != expected_ip:
                        print(f"[⚠️] Spoofing detectado: {sender} desde {addr[0]} ≠ {expected_ip}")
                        continue

                    self._pending_messages[body_id] = {
                        "from": sender,
                        "addr": addr,
                        "op": op
                    }
                    self.udp_sock.sendto(pack_response(0, self.user_id), addr)
                    continue

                if len(data) > 8:
                    body_id = int.from_bytes(data[:8], byteorder="big")
                    payload = data[8:]
                    entry = self._pending_messages.pop(body_id, None)

                    if entry:
                        sender = entry["from"]
                        key = (sender, body_id)
                        if key in self._seen_messages:
                            print(f"[⛔] Mensaje duplicado ignorado de {sender} (body_id={body_id})")
                            continue
                        self._seen_messages[key] = time.time()

                        if entry["op"] == 1:
                            self.on_message(sender, payload.decode(errors="ignore"))
                        self.udp_sock.sendto(pack_response(0, self.user_id), entry["addr"])

            except Exception as e:
                print(f"[Messaging] Error UDP: {e}")

    def send_message(self, user_id: str, text: str) -> bool | None:
        try:
            ip = self._get_peer_ip(user_id)
            msg_bytes = text.encode()
            body_len = len(msg_bytes)
            body_id = random.randint(0, 2**31 - 1)

            hdr = pack_header(self.user_id, user_id, 1, body_id, body_len)
            self.udp_sock.sendto(hdr, (ip, LCP_PORT))

            self.udp_sock.settimeout(3.0)
            try:
                response1, _ = self.udp_sock.recvfrom(RESPONSE_SIZE)
                status1, _ = unpack_response(response1)
                if status1 != 0:
                    return False
            except socket.timeout:
                print(f"[Messaging] No ACK para header con {user_id}")
                return None

            body = body_id.to_bytes(8, byteorder="big") + msg_bytes
            self.udp_sock.sendto(body, (ip, LCP_PORT))

            try:
                response2, _ = self.udp_sock.recvfrom(RESPONSE_SIZE)
                status2, _ = unpack_response(response2)
                return status2 == 0
            except socket.timeout:
                print(f"[Messaging] No ACK para cuerpo con {user_id}")
                return None

        except Exception as e:
            print(f"[Messaging] Error enviando mensaje a {user_id}: {e}")
            return None

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
            if hdr["op_code"] != 2:
                return

            filename = hdr["user_to"]
            sender = hdr["user_from"]
            body_id_bytes = conn.recv(8)
            body_id = int.from_bytes(body_id_bytes, byteorder="big")
            bytes_to_read = hdr["body_len"] - 8

            key = (sender, body_id)
            if key in self._seen_messages:
                print(f"[⛔] Archivo duplicado ignorado de {sender} (body_id={body_id})")
                conn.close()
                return
            self._seen_messages[key] = time.time()

            path = Path("Descargas") / filename
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(path, "wb") as f:
                while bytes_to_read > 0:
                    chunk = conn.recv(min(4096, bytes_to_read))
                    if not chunk:
                        break
                    f.write(chunk)
                    bytes_to_read -= len(chunk)

            self.on_file(sender, str(path))
            conn.sendall(pack_response(0, self.user_id))

        except Exception as e:
            print(f"[Messaging] Error manejando TCP: {e}")
        finally:
            conn.close()

    def send_file(self, user_id: str, filepath: str):
        try:
            ip = self._get_peer_ip(user_id)
            path = Path(filepath)
            body_id = random.randint(0, 2**31 - 1)
            file_size = path.stat().st_size

            hdr = pack_header(self.user_id, path.name, 2, body_id, file_size + 8)
            self.udp_sock.sendto(hdr, (ip, LCP_PORT))

            self.udp_sock.settimeout(5.0)
            try:
                response, _ = self.udp_sock.recvfrom(RESPONSE_SIZE)
                status, _ = unpack_response(response)
                if status != 0:
                    print(f"[Messaging] Rechazado por {user_id}")
                    return
            except socket.timeout:
                print(f"[Messaging] Timeout esperando ACK de {user_id}")
                return

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, LCP_PORT))
            sock.sendall(hdr)
            sock.sendall(body_id.to_bytes(8, byteorder="big"))

            with open(filepath, "rb") as f:
                while chunk := f.read(4096):
                    sock.sendall(chunk)

            try:
                resp = sock.recv(RESPONSE_SIZE)
                status, _ = unpack_response(resp)
                if status == 0:
                    print(f"[Messaging] Archivo enviado exitosamente a {user_id}")
                else:
                    print(f"[Messaging] Error remoto al enviar archivo a {user_id}")
            except socket.timeout:
                print(f"[Messaging] Sin respuesta TCP de {user_id}")
            sock.close()

        except Exception as e:
            print(f"[Messaging] Error enviando archivo a {user_id}: {e}")

    def _cleanup_seen_messages(self):
        while True:
            now = time.time()
            to_delete = [key for key, ts in self._seen_messages.items() if now - ts > DUPLICATE_EXPIRY]
            for key in to_delete:
                del self._seen_messages[key]
            time.sleep(10)
