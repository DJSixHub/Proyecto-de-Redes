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
                if len(data) == HEADER_SIZE:
                    header = unpack_header(data)
                    if header['op_code'] == 1:
                        # Paso 1: Confirmar recepción del header
                        response = pack_response(0, self.user_id)
                        self.udp_sock.sendto(response, addr)
                        continue

                elif len(data) > 8:
                    # Paso 2: Recibir cuerpo del mensaje
                    body_id = int.from_bytes(data[:8], byteorder='big')
                    message = data[8:].decode(errors='ignore')
                    self.on_message("desconocido", message)  # remitente no se transmite aquí

            except Exception as e:
                print(f"[Messaging] Error UDP: {e}")

    def send_message(self, nickname: str, text: str) -> bool | None:
        try:
            ip = self._get_peer_ip(nickname)
            msg_bytes = text.encode()
            body_len = len(msg_bytes)
            body_id = random.randint(0, 255)

            # Paso 1: Enviar encabezado
            hdr = pack_header(self.user_id, nickname, 1, body_id, body_len)
            self.udp_sock.sendto(hdr, (ip, LCP_PORT))

            # Paso 2: Esperar confirmación
            self.udp_sock.settimeout(5.0)
            try:
                response, _ = self.udp_sock.recvfrom(1024)
                if len(response) == RESPONSE_SIZE:
                    status, _ = unpack_response(response)
                    if status == 0:
                        # Paso 3: Enviar cuerpo
                        payload = body_id.to_bytes(8, byteorder='big') + msg_bytes
                        self.udp_sock.sendto(payload, (ip, LCP_PORT))
                        return True
                    else:
                        return False
                else:
                    print("[Messaging] Respuesta inválida")
                    return False
            except socket.timeout:
                print(f"[Messaging] Sin respuesta de {nickname} (timeout)")
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

            path = Path("Descargas") / filename
            path.parent.mkdir(parents=True, exist_ok=True)

            file_id_bytes = conn.recv(8)
            file_content = b""
            bytes_to_read = hdr['body_len'] - 8

            while bytes_to_read > 0:
                chunk = conn.recv(min(4096, bytes_to_read))
                if not chunk:
                    break
                file_content += chunk
                bytes_to_read -= len(chunk)

            path.write_bytes(file_content)

            self.on_file(sender, filename)

            conn.sendall(pack_response(0, self.user_id))
        except Exception as e:
            print(f"[Messaging] Error manejando TCP: {e}")
        finally:
            conn.close()
