import socket
import threading
import random
from pathlib import Path
from protocol import (
    pack_header, unpack_header,
    pack_response, unpack_response,
    HEADER_SIZE, RESPONSE_SIZE
)

LCP_PORT = 9990

class Messaging:
    def __init__(self, user_id: str, on_message, on_file, udp_sock=None):
        self.user_id = user_id
        self.on_message = on_message
        self.on_file = on_file
        self._peer_map = {}
        self._pending_messages = {}

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

                # Fase 1: Header (mensaje)
                if len(data) == HEADER_SIZE:
                    header = unpack_header(data)
                    if header['op_code'] == 1:
                        self._pending_messages[header['body_id']] = {
                            'from': header['user_from'],
                            'addr': addr
                        }
                        self.udp_sock.sendto(pack_response(0, self.user_id), addr)
                    elif header['op_code'] == 2:
                        self.udp_sock.sendto(pack_response(0, self.user_id), addr)
                    continue

                # Fase 2: Cuerpo del mensaje
                if len(data) > 8:
                    body_id = int.from_bytes(data[:8], byteorder='big')
                    payload = data[8:]
                    entry = self._pending_messages.pop(body_id, None)
                    if entry:
                        sender = entry['from']
                        self.on_message(sender, payload.decode(errors='ignore'))
                        self.udp_sock.sendto(pack_response(0, self.user_id), entry['addr'])

            except Exception as e:
                print(f"[Messaging] Error UDP: {e}")

    def send_message(self, nickname: str, text: str) -> bool | None:
        try:
            ip = self._get_peer_ip(nickname)
            msg_bytes = text.encode()
            body_len = len(msg_bytes)
            body_id = random.randint(0, 255)

            # Fase 1: Enviar header
            hdr = pack_header(self.user_id, nickname, 1, body_id, body_len)
            self.udp_sock.sendto(hdr, (ip, LCP_PORT))

            # Fase 2: Esperar respuesta al header
            self.udp_sock.settimeout(5.0)
            try:
                response1, _ = self.udp_sock.recvfrom(RESPONSE_SIZE)
                status1, _ = unpack_response(response1)
                if status1 != 0:
                    return False
            except socket.timeout:
                return None

            # Fase 3: Enviar cuerpo
            body = body_id.to_bytes(8, byteorder='big') + msg_bytes
            self.udp_sock.sendto(body, (ip, LCP_PORT))

            # Fase 4: Esperar confirmación final
            try:
                response2, _ = self.udp_sock.recvfrom(RESPONSE_SIZE)
                status2, _ = unpack_response(response2)
                return status2 == 0
            except socket.timeout:
                return None

        except Exception as e:
            print(f"[Messaging] Error enviando mensaje a {nickname}: {e}")
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
            if hdr['op_code'] != 2:
                return

            filename = hdr['user_to']
            sender = hdr['user_from']
            file_id_bytes = conn.recv(8)
            bytes_to_read = hdr['body_len'] - 8

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

    def send_file(self, nickname: str, filepath: str):
        try:
            ip = self._get_peer_ip(nickname)
            path = Path(filepath)
            body_id = random.randint(0, 255)
            file_size = path.stat().st_size
            hdr = pack_header(self.user_id, path.name, 2, body_id, file_size + 8)

            # Paso 1: enviar header por UDP
            self.udp_sock.sendto(hdr, (ip, LCP_PORT))

            self.udp_sock.settimeout(5.0)
            try:
                response, _ = self.udp_sock.recvfrom(RESPONSE_SIZE)
                status, _ = unpack_response(response)
                if status != 0:
                    print(f"[Messaging] Rechazado por {nickname}")
                    return
            except socket.timeout:
                print(f"[Messaging] Timeout esperando ACK de {nickname}")
                return

            # Paso 2: enviar archivo por TCP
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((ip, LCP_PORT))
            sock.sendall(hdr)
            sock.sendall(body_id.to_bytes(8, byteorder='big'))

            with open(filepath, "rb") as f:
                while chunk := f.read(4096):
                    sock.sendall(chunk)

            # Paso 3: esperar confirmación TCP
            try:
                resp = sock.recv(RESPONSE_SIZE)
                status, _ = unpack_response(resp)
                if status == 0:
                    print(f"[Messaging] Archivo enviado exitosamente a {nickname}")
                else:
                    print(f"[Messaging] Error remoto al enviar archivo a {nickname}")
            except socket.timeout:
                print(f"[Messaging] Sin respuesta TCP de {nickname}")
            sock.close()

        except Exception as e:
            print(f"[Messaging] Error enviando archivo a {nickname}: {e}")
