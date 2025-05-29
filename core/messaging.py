# core/messaging.py

import threading
import socket
import os
from datetime import datetime, UTC
import queue
import time
import hashlib

from core.protocol import (
    UDP_PORT,
    BROADCAST_UID,
    pack_header,
    unpack_header,
    pack_response,
    unpack_response,
    HEADER_SIZE,
    RESPONSE_SIZE,
    TCP_PORT,
    pack_message_body,
    unpack_message_body,
    OP_MESSAGE,
    OP_FILE,
    RESP_OK,
    USER_ID_SIZE
)

class Messaging:
    """
    Comunicación con protocolo LCP (HEADER → ACK → BODY → ACK).
    Soporta envío de texto y archivos, y guarda los archivos recibidos
    en ./Descargas en la raíz del proyecto.
    """

    def __init__(self, user_id: bytes, discovery, history_store):
        # Normalizar user_id a exactamente 20 bytes
        if isinstance(user_id, str):
            user_id = user_id.encode('utf-8')
        self.raw_id = user_id.rstrip(b'\x00')[:USER_ID_SIZE]
        self.user_id = self.raw_id.ljust(USER_ID_SIZE, b'\x00')
        print(f"ID inicializado: raw={self.raw_id!r}, padded={self.user_id!r}")
        self.discovery = discovery
        self.history_store = history_store

        # Socket UDP para mensajes de control
        self.sock = discovery.sock
        self.sock.setblocking(True)
        self.sock.settimeout(5.0)  # 5 segundos de timeout por defecto
        
        # Aumentar buffers de recepción y envío
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB

        # Socket TCP para transferencia de archivos
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB
        self.tcp_sock.bind(('0.0.0.0', TCP_PORT))
        self.tcp_sock.listen(5)
        
        # Para coordinar ACKs que esperan send()/send_file()
        self._acks = {}             # responder_uid -> threading.Event
        self._acks_lock = threading.Lock()
        
        # Contador para IDs únicos de mensajes
        self._next_body_id = 0
        self._body_id_lock = threading.Lock()
        
        # Headers pendientes para transferencias de archivos
        self._pending_headers = {}  # body_id -> (header, timestamp)
        self._pending_headers_lock = threading.Lock()
        
        # Cola para mensajes entrantes
        self._message_queue = queue.Queue()
        
        # Iniciar limpieza periódica de headers pendientes
        threading.Thread(target=self._clean_pending_headers, daemon=True).start()
        
        # Iniciar procesador de mensajes
        threading.Thread(target=self._process_messages, daemon=True).start()

    def _clean_pending_headers(self):
        """Limpia headers pendientes más antiguos que 30 segundos"""
        while True:
            now = datetime.now(UTC)
            with self._pending_headers_lock:
                for body_id in list(self._pending_headers.keys()):
                    header, timestamp = self._pending_headers[body_id]
                    if (now - timestamp).total_seconds() > 30:
                        del self._pending_headers[body_id]
            threading.Event().wait(5)  # Dormir 5 segundos entre limpiezas

    def _get_next_body_id(self):
        with self._body_id_lock:
            body_id = self._next_body_id
            self._next_body_id = (self._next_body_id + 1) % 256  # Mantener en 1 byte
            return body_id

    def _send_and_wait(self, data: bytes, recipient: bytes, timeout: float = 5.0, retries: int = 3):
        """
        Envía `data` a `recipient` y espera el ACK correspondiente.
        Incluye reintentos y mejor manejo de errores.
        """
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise ValueError("Peer no encontrado en discovery")
        dest = (info['ip'], UDP_PORT)

        ev = threading.Event()
        key = recipient.rstrip(b'\x00')
        
        for attempt in range(retries):
            with self._acks_lock:
                self._acks[key] = ev
            
            try:
                self.sock.sendto(data, dest)
                received = ev.wait(timeout)
                
                if received:
                    return True
                    
            except socket.error as e:
                if attempt == retries - 1:
                    raise ConnectionError(f"Error de red al enviar a {recipient!r}: {e}")
            finally:
                with self._acks_lock:
                    self._acks.pop(key, None)
                    
            # Esperar antes de reintentar
            if attempt < retries - 1:
                threading.Event().wait(0.5 * (attempt + 1))
                
        raise TimeoutError(f"No se recibió ACK de {recipient!r} después de {retries} intentos")

    def send(self, recipient: bytes, message: bytes, timeout: float = 5.0):
        """
        Envía un mensaje de texto con reintentos:
          1) HEADER(op_code=1, body_len) → ACK
          2) BODY(8B message_id + message) → ACK
        """
        body_id = self._get_next_body_id()
        body = pack_message_body(body_id, message)
        
        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=OP_MESSAGE,
            body_id=body_id,
            body_len=len(body)
        )
        try:
            self._send_and_wait(header, recipient, timeout)
            self._send_and_wait(body, recipient, timeout)
        except (TimeoutError, ConnectionError) as e:
            # Intentar redescubrir el peer antes de fallar
            self.discovery.discover_peers()
            raise

    def send_file(self, recipient: bytes, file_bytes: bytes, filename: str, timeout: float = None):
        """
        Envía un archivo usando TCP según el protocolo LCP:
          1) HEADER UDP(op_code=2, body_len) → ACK
          2) Conexión TCP y envío de datos (8B file_id + 2B name_len + name + content)
          3) Esperar ACK final por TCP (RESPONSE_SIZE bytes)
        """
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise ValueError("Peer no encontrado en discovery")
            
        # 1. Preparar datos y enviar header UDP
        body_id = self._get_next_body_id()  # Ya retorna 1 byte (0-255)
        print(f"Enviando archivo {filename} (body_id={body_id})")
        
        # Preparar nombre del archivo
        name_b = filename.encode('utf-8')
        if len(name_b) > 0xFFFF:
            raise ValueError("Nombre de archivo demasiado largo")
        name_len = len(name_b).to_bytes(2, 'big')
        
        # Preparar datos TCP según protocolo
        body = body_id.to_bytes(8, 'big') + name_len + name_b + file_bytes
        
        # Enviar header UDP y esperar ACK
        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=OP_FILE,
            body_id=body_id,
            body_len=len(body)
        )
        
        try:
            # Enviar header UDP y esperar ACK
            self._send_and_wait(header, recipient, timeout or 5.0)
            print(f"Header UDP enviado, esperando ACK...")
            
            # Esperar 500ms para asegurar que el receptor esté listo
            time.sleep(0.5)
            
            # 2. Establecer conexión TCP y enviar datos
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB buffer
                sock.settimeout(timeout or 30.0)
                
                print(f"Conectando a {info['ip']}:{TCP_PORT}...")
                sock.connect((info['ip'], TCP_PORT))
                
                # Enviar datos en chunks de 32KB
                sent = 0
                chunk_size = 32768
                while sent < len(body):
                    chunk = body[sent:sent + chunk_size]
                    bytes_sent = sock.send(chunk)
                    if bytes_sent == 0:
                        raise ConnectionError("Conexión cerrada durante envío")
                    sent += bytes_sent
                    print(f"Enviados {sent}/{len(body)} bytes")
                
                # 3. Esperar ACK final
                print("Esperando ACK final...")
                sock.shutdown(socket.SHUT_WR)  # Indicar fin de transmisión
                
                # Esperar ACK con timeout
                sock.settimeout(5.0)  # 5 segundos para el ACK
                ack = sock.recv(RESPONSE_SIZE)  # Esperar el ACK completo (25 bytes)
                if not ack or len(ack) != RESPONSE_SIZE:
                    raise ConnectionError(f"ACK inválido: recibidos {len(ack) if ack else 0} bytes")
                    
                try:
                    resp = unpack_response(ack)
                    print(f"ACK recibido: status={resp['status']}, responder={resp['responder']!r}")
                    
                    # Manejar diferentes estados del ACK
                    if resp['status'] == RESP_OK:
                        print("Archivo enviado correctamente")
                    elif resp['status'] == 1:  # Archivo ya existe
                        print("El archivo ya existe en el destino")
                    elif resp['status'] == 2:  # Error general
                        raise ConnectionError("Error general en el receptor")
                    else:
                        raise ConnectionError(f"Estado de ACK desconocido: {resp['status']}")
                        
                except Exception as e:
                    print(f"Error decodificando ACK: {e}")
                    print(f"Bytes recibidos: {' '.join(f'{b:02x}' for b in ack)}")
                    raise
                    
        except Exception as e:
            print(f"Error en transferencia TCP: {e}")
            raise

    def broadcast(self, message: bytes):
        """Envía un mensaje de texto a todos los peers (excepto BROADCAST_UID)."""
        for peer_id in self.discovery.get_peers():
            if peer_id == BROADCAST_UID:
                continue
            try:
                self.send(peer_id, message)
            except:
                pass

    def send_all(self, message: bytes):
        """Alias para compatibilidad: envía un mensaje de texto global."""
        return self.broadcast(message)

    def start_listening(self):
        threading.Thread(target=self.recv_loop, daemon=True).start()

    def _process_messages(self):
        """Procesa mensajes de la cola en un hilo separado"""
        while True:
            try:
                hdr, body = self._message_queue.get()
                self._handle_message_or_file(hdr, body)
            except Exception as e:
                print(f"Error procesando mensaje de la cola: {e}")

    def recv_loop(self):
        """Loop principal de recepción de mensajes"""
        print("Iniciando loop de recepción de mensajes...")
        
        # Thread para aceptar conexiones TCP
        tcp_thread = threading.Thread(target=self._tcp_accept_loop, daemon=True)
        tcp_thread.start()
        
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
                print(f"\nRecibidos {len(data)} bytes desde {addr[0]}")
                
                # Validar longitud mínima
                if len(data) < 1:
                    print("  - Paquete vacío, ignorando")
                    continue

                # 1) ¿Es un ACK?
                if len(data) == RESPONSE_SIZE:
                    try:
                        resp = unpack_response(data)
                        print(f"  - Es un ACK (status={resp['status']})")
                        if resp['status'] == 0:
                            r = resp['responder'].rstrip(b'\x00')
                            with self._acks_lock:
                                ev = self._acks.get(r)
                                if ev:
                                    print(f"  - ACK esperado de {r!r}, notificando")
                                    ev.set()
                                    continue
                                else:
                                    print(f"  - ACK no esperado de {r!r}")
                        self.discovery.handle_response(data, addr)
                    except Exception as e:
                        print(f"Error procesando ACK: {e}")
                    continue

                # 2) Mensaje o archivo (cabecera)
                if len(data) < HEADER_SIZE:
                    print(f"  - Paquete demasiado corto para header ({len(data)} < {HEADER_SIZE})")
                    continue

                try:
                    hdr = unpack_header(data[:HEADER_SIZE])
                    print(f"  - Header decodificado: op={hdr['op_code']}, from={hdr['user_from']!r}, to={hdr['user_to']!r}")
                except Exception as e:
                    print(f"Error desempaquetando header: {e}")
                    continue

                # Discovery ping
                if hdr['op_code'] == 0 and hdr['user_to'] == BROADCAST_UID:
                    print("  - Es un ping de discovery")
                    self.discovery.handle_echo(data, addr)
                    continue

                # Sólo procesar si es para mí o es un broadcast
                my_id = self.raw_id.rstrip(b' ')
                to_id = hdr['user_to'].rstrip(b' ')  # Ya viene sin \x00 por unpack_header
                from_id = hdr['user_from'].rstrip(b' ')  # Ya viene sin \x00 por unpack_header
                is_for_me = (to_id == my_id)
                is_broadcast = (to_id == BROADCAST_UID)
                
                print(f"  - Destino: {'broadcast' if is_broadcast else ('para mí' if is_for_me else 'no es para mí')}")
                print(f"  - Mi ID (sin espacios): {my_id!r}")
                print(f"  - ID destino (sin espacios): {to_id!r}")
                print(f"  - ID origen (sin espacios): {from_id!r}")
                
                if hdr['op_code'] in (OP_MESSAGE, OP_FILE) and (is_for_me or is_broadcast):
                    try:
                        print(f"Procesando mensaje de {addr[0]} tipo {hdr['op_code']} {'(broadcast)' if is_broadcast else ''}")
                        
                        # ACK cabecera
                        self.sock.sendto(pack_response(0, self.user_id), addr)
                        print("  - ACK de header enviado")

                        if hdr['op_code'] == OP_MESSAGE:  # Mensaje de texto
                            # Recibir cuerpo con timeout
                            body_len = hdr['body_len']
                            body = bytearray()
                            
                            try:
                                # Establecer timeout para recepción del cuerpo
                                self.sock.settimeout(5.0)
                                print(f"  - Esperando cuerpo del mensaje ({body_len} bytes)")
                                
                                # Recibir todo el cuerpo de una vez con un buffer grande
                                chunk, _ = self.sock.recvfrom(65536)  # Buffer de 64KB
                                if not chunk:  # Conexión cerrada
                                    raise ConnectionError("Conexión cerrada durante recepción")
                                    
                                print(f"    - Recibidos {len(chunk)} bytes")
                                
                                # Verificar que recibimos exactamente lo que esperábamos
                                if len(chunk) != body_len:
                                    print(f"    - ADVERTENCIA: Tamaño recibido ({len(chunk)}) != esperado ({body_len})")
                                    
                                body.extend(chunk)
                                
                                # ACK cuerpo
                                self.sock.sendto(pack_response(0, self.user_id), addr)
                                print("  - ACK de cuerpo enviado")
                                
                                # Encolar para procesamiento
                                self._message_queue.put((hdr, bytes(body)))
                                print(f"  - Mensaje encolado para procesamiento")
                                
                            except socket.timeout:
                                print("Timeout recibiendo cuerpo del mensaje")
                                self.sock.sendto(pack_response(2, self.user_id), addr)
                            finally:
                                # Restaurar timeout por defecto
                                self.sock.settimeout(5.0)
                                
                        elif hdr['op_code'] == OP_FILE:  # Archivo
                            # No procesar archivos broadcast
                            if is_broadcast:
                                print("  - Ignorando archivo broadcast")
                                self.sock.sendto(pack_response(1, self.user_id), addr)
                                continue
                                
                            # Guardar header para la transferencia TCP
                            with self._pending_headers_lock:
                                self._pending_headers[hdr['body_id']] = (hdr, datetime.now(UTC))
                            print("  - Header guardado para transferencia TCP")
                            
                    except Exception as e:
                        print(f"Error procesando mensaje: {e}")
                        try:
                            self.sock.sendto(pack_response(2, self.user_id), addr)
                        except:
                            pass
                else:
                    print("  - Mensaje ignorado (no es para mí ni broadcast)")
            except socket.timeout:
                continue  # Normal, seguir escuchando
            except Exception as e:
                print(f"Error en recv_loop: {e}")
                continue

    def _tcp_accept_loop(self):
        """Loop para aceptar conexiones TCP para transferencia de archivos"""
        while True:
            try:
                client_sock, addr = self.tcp_sock.accept()
                threading.Thread(
                    target=self._handle_tcp_file_transfer,
                    args=(client_sock, addr),
                    daemon=True
                ).start()
            except Exception as e:
                print(f"Error aceptando conexión TCP: {e}")
                continue

    def _handle_tcp_file_transfer(self, sock: socket.socket, addr):
        """
        Maneja una conexión TCP para recibir un archivo según el protocolo LCP:
        1. Recibir file_id (8 bytes)
        2. Recibir name_len (2 bytes)
        3. Recibir nombre del archivo (name_len bytes)
        4. Recibir contenido del archivo
        5. Enviar ACK (RESPONSE_SIZE bytes)
        """
        def recv_exact(n):
            """Lee exactamente n bytes del socket"""
            data = bytearray()
            while len(data) < n:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    raise ConnectionError("Conexión cerrada durante lectura")
                data.extend(chunk)
            return bytes(data)

        def detect_file_type(header_bytes):
            """Detecta el tipo de archivo basado en sus primeros bytes"""
            signatures = {
                b'%PDF': '.pdf',
                b'PK\x03\x04': '.zip',
                b'\x89PNG': '.png',
                b'\xFF\xD8\xFF': '.jpg'
            }
            for sig, ext in signatures.items():
                if header_bytes.startswith(sig):
                    return ext
            return None

        try:
            print(f"Iniciando transferencia TCP desde {addr[0]}:{addr[1]}")
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            sock.settimeout(30.0)  # 30 segundos timeout para archivos grandes
            
            # 1. Primero leer el file_id (8 bytes)
            try:
                body_id_bytes = recv_exact(8)
                print(f"Bytes de file_id: {' '.join(f'{b:02x}' for b in body_id_bytes)}")
                body_id = int.from_bytes(body_id_bytes, 'big')
                print(f"ID de archivo recibido: {body_id}")
            except Exception as e:
                print(f"Error leyendo file_id: {e}")
                if 'body_id_bytes' in locals():
                    print(f"Bytes recibidos: {' '.join(f'{b:02x}' for b in body_id_bytes)}")
                raise
            
            # 2. Intentar leer la longitud del nombre
            try:
                # Leer 16 bytes para detectar el tipo de archivo
                peek_bytes = sock.recv(16, socket.MSG_PEEK)
                print(f"Primeros bytes del stream: {' '.join(f'{b:02x}' for b in peek_bytes)}")
                
                file_type = detect_file_type(peek_bytes)
                if file_type:
                    print(f"Detectado archivo tipo: {file_type}")
                    # Si detectamos un tipo de archivo conocido, probablemente no hay nombre
                    name_len = 0
                    original_name = f"archivo_{body_id}{file_type}"
                else:
                    # Intentar leer la longitud del nombre normalmente
                    name_len_bytes = recv_exact(2)
                    print(f"Bytes de name_len: {' '.join(f'{b:02x}' for b in name_len_bytes)}")
                    name_len = int.from_bytes(name_len_bytes, 'big')
                    print(f"Longitud del nombre: {name_len} bytes")
                    
                    # Validación más estricta
                    if name_len > 256 or name_len < 0:
                        print(f"Longitud de nombre inválida ({name_len}), asumiendo archivo sin nombre")
                        name_len = 0
                        original_name = f"archivo_{body_id}.bin"
                    else:
                        # 3. Leer nombre del archivo
                        name_bytes = recv_exact(name_len)
                        try:
                            original_name = name_bytes.decode('utf-8')
                        except UnicodeDecodeError:
                            print(f"Error decodificando nombre, usando fallback")
                            original_name = f"archivo_{body_id}.bin"
                
                print(f"Nombre del archivo: {original_name}")
                
            except Exception as e:
                print(f"Error procesando nombre: {e}")
                # Continuar con nombre por defecto
                original_name = f"archivo_{body_id}.bin"
            
            # 4. Recibir contenido del archivo
            body = bytearray()
            chunk_size = 32768  # 32KB chunks
            total_received = 0
            
            while True:
                try:
                    chunk = sock.recv(chunk_size)
                    if not chunk:  # Fin de transmisión
                        break
                    body.extend(chunk)
                    total_received += len(chunk)
                    if total_received % (1024*1024) == 0:  # Cada 1MB
                        print(f"Recibidos {total_received//1024}KB")
                except socket.timeout:
                    if len(body) > 0:  # Si ya recibimos datos, considerarlo completo
                        break
                    raise  # Si no hay datos, propagar el timeout
            
            print(f"Recepción completa: {len(body)} bytes")
            
            # Detectar tipo de archivo si no se hizo antes
            if not file_type and len(body) >= 4:
                file_type = detect_file_type(body[:4])
                if file_type:
                    original_name = f"archivo_{body_id}{file_type}"
            
            # Generar nombre único preservando la extensión original
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            name, ext = os.path.splitext(original_name)
            if not ext:  # Si no tiene extensión
                ext = '.bin'  # Usar .bin por defecto
            filename = f"archivo_{timestamp}_{body_id & 0xFF}{ext}"
            print(f"Guardando como: {filename}")

            # Crear directorio de descargas si no existe
            downloads_dir = os.path.join(os.getcwd(), "Descargas")
            os.makedirs(downloads_dir, exist_ok=True)
            path = os.path.join(downloads_dir, filename)
            
            # Verificar si el archivo ya existe por contenido (hash)
            content_hash = hashlib.sha256(body).hexdigest()
            
            # Buscar archivos existentes con el mismo hash
            for existing_file in os.listdir(downloads_dir):
                existing_path = os.path.join(downloads_dir, existing_file)
                if os.path.isfile(existing_path):
                    try:
                        with open(existing_path, 'rb') as f:
                            if hashlib.sha256(f.read()).hexdigest() == content_hash:
                                print(f"Archivo con el mismo contenido ya existe: {existing_file}")
                                # Enviar ACK con status=1 (archivo existente)
                                ack = pack_response(1, self.user_id)
                                print(f"Enviando ACK (archivo existente): {' '.join(f'{b:02x}' for b in ack)}")
                                sock.send(ack)
                                return body_id, body
                    except:
                        continue
            
            # Escribir contenido binario
            with open(path, 'wb') as f:
                f.write(body)
            print(f"Archivo guardado en {path}")
            
            # Registrar en historial
            self.history_store.append_file(
                sender=addr[0],
                recipient=self.raw_id.decode('utf-8'),
                filename=filename,
                timestamp=datetime.now(UTC)
            )
            
            # 5. Enviar ACK y esperar confirmación
            sock.settimeout(5.0)  # Timeout más corto para el ACK
            try:
                # Enviar ACK completo según protocolo
                ack = pack_response(RESP_OK, self.user_id)
                print(f"Enviando ACK: {' '.join(f'{b:02x}' for b in ack)}")
                sock.send(ack)
                print("ACK enviado")
            except Exception as e:
                print(f"Error enviando ACK: {e}")
                raise
            
            return body_id, body
            
        except Exception as e:
            print(f"Error en transferencia TCP: {e}")
            try:
                # En caso de error, enviar ACK de error
                ack = pack_response(2, self.user_id)  # Status 2 = Error
                sock.send(ack)
            except:
                pass
            raise
        finally:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
            sock.close()

    def _handle_message_or_file(self, hdr, body: bytes):
        """Procesa un mensaje o archivo recibido"""
        try:
            # Normalizar IDs consistentemente
            peer_id = hdr['user_from'].rstrip(b'\x00')
            my_id = self.raw_id.rstrip(b' ')
            to_id = hdr['user_to'].rstrip(b' ')
            from_id = hdr['user_from'].rstrip(b' ')
            
            peer = peer_id.decode('utf-8', errors='ignore')
            is_broadcast = (to_id == BROADCAST_UID)

            print(f"Procesando mensaje/archivo de {peer} ({hdr['op_code']}) {'(broadcast)' if is_broadcast else ''}")
            print(f"  - ID origen: {peer_id!r}")
            print(f"  - ID destino: {to_id!r}")
            print(f"  - ID local: {my_id!r}")
            print(f"  - Longitud body: {len(body)} bytes")

            if hdr['op_code'] == OP_MESSAGE:
                # Texto: extraer message_id y contenido
                message_id, content = unpack_message_body(body)
                # El message_id en el body es de 8 bytes, pero solo comparamos el último byte
                if (message_id & 0xFF) != hdr['body_id']:
                    print(f"  - Warning: ID de mensaje no coincide: header={hdr['body_id']}, body={message_id & 0xFF}")
                    
                text = content.decode('utf-8', errors='ignore')
                print(f"  - Mensaje decodificado ({len(text)} chars): {text[:50]}...")
                
                self.history_store.append_message(
                    sender=peer,
                    recipient="*global*" if is_broadcast else my_id.decode('utf-8'),
                    message=text,
                    timestamp=datetime.now(UTC)
                )
                print("  - Mensaje guardado en historial")
            else:
                # No procesar archivos broadcast
                if is_broadcast:
                    print("  - Ignorando archivo broadcast")
                    return
                    
                # Archivo: extraer ID y contenido (sin nombre)
                file_id = int.from_bytes(body[:8], 'big')
                # El file_id en el body es de 8 bytes, pero solo comparamos el último byte
                if (file_id & 0xFF) != hdr['body_id']:
                    print(f"  - Warning: ID de archivo no coincide: header={hdr['body_id']}, body={file_id & 0xFF}")
                    
                file_data = body[8:]  # Solo contenido binario
                
                # Generar nombre único basado en timestamp
                timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                filename = f"archivo_{timestamp}_{file_id & 0xFF}.bin"
                print(f"  - Guardando archivo como: {filename} ({len(file_data)} bytes)")

                downloads_dir = os.path.join(os.getcwd(), "Descargas")
                os.makedirs(downloads_dir, exist_ok=True)
                path = os.path.join(downloads_dir, filename)
                
                # Escribir contenido binario directamente
                with open(path, 'wb') as f:
                    f.write(file_data)

                self.history_store.append_file(
                    sender=peer,
                    recipient=my_id.decode('utf-8'),
                    filename=filename,
                    timestamp=datetime.now(UTC)
                )
                print("  - Archivo guardado en Descargas/")
        except Exception as e:
            print(f"Error procesando mensaje/archivo: {e}")
            print(f"  - Header: {hdr}")
            print(f"  - Body length: {len(body)}")
            # No re-raise para evitar que un error en un archivo afecte al resto
