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

# Este archivo implementa el sistema de mensajería del chat utilizando el protocolo LCP.
# El flujo de datos comienza con la inicialización de sockets UDP para mensajes de control
# y TCP para transferencia de archivos. El sistema maneja el envío y recepción de mensajes
# y archivos, implementa un sistema de confirmación (ACK) con reintentos automáticos,
# coordina múltiples hilos para el procesamiento de mensajes entrantes, y gestiona la
# limpieza periódica de datos temporales. También se encarga de la persistencia del
# historial de comunicaciones y el manejo de errores en la red.

class Messaging:
    # Clase principal que implementa la comunicación entre peers usando el protocolo LCP.
    # Maneja sockets UDP para mensajes de control y TCP para transferencia de archivos,
    # implementa el sistema de ACKs con reintentos, y coordina múltiples hilos para
    # el procesamiento de mensajes y mantenimiento del sistema.
    def __init__(self, user_id: bytes, discovery, history_store):
        # Normalización del ID de usuario a formato estándar de 20 bytes
        if isinstance(user_id, str):
            user_id = user_id.encode('utf-8')
        self.raw_id = user_id.rstrip(b'\x00')[:USER_ID_SIZE]
        self.user_id = self.raw_id.ljust(USER_ID_SIZE, b'\x00')
        print(f"ID inicializado: raw={self.raw_id!r}, padded={self.user_id!r}")
        
        # Referencias a servicios externos necesarios
        self.discovery = discovery
        self.history_store = history_store

        # Configuración del socket UDP para mensajes de control
        # Reutilizamos el socket del sistema de discovery
        self.sock = discovery.sock
        self.sock.setblocking(True)
        self.sock.settimeout(5.0)
        
        # Aumentamos los buffers para mejorar el rendimiento
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB

        # Configuración del socket TCP para transferencia de archivos
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB
        self.tcp_sock.bind(('0.0.0.0', TCP_PORT))
        self.tcp_sock.listen(5)
        
        # Sistema de ACKs para coordinar envíos y respuestas
        self._acks = {}  # Mapeo de responder_uid -> threading.Event
        self._acks_lock = threading.Lock()
        
        # Contador para generar IDs únicos de mensajes/archivos
        self._next_body_id = 0
        self._body_id_lock = threading.Lock()
        
        # Almacenamiento temporal de headers para transferencias TCP
        self._pending_headers = {}  # Mapeo de body_id -> (header, timestamp)
        self._pending_headers_lock = threading.Lock()
        
        # Cola para procesamiento asíncrono de mensajes
        self._message_queue = queue.Queue()
        
        # Iniciamos hilos de mantenimiento y procesamiento
        threading.Thread(target=self._clean_pending_headers, daemon=True).start()
        threading.Thread(target=self._process_messages, daemon=True).start()

    # Limpia periódicamente los headers pendientes que han expirado (más de 30 segundos)
    # para evitar la acumulación de datos innecesarios en memoria y mantener el sistema
    # limpio y eficiente.
    def _clean_pending_headers(self):
        while True:
            now = datetime.now(UTC)
            with self._pending_headers_lock:
                for body_id in list(self._pending_headers.keys()):
                    header, timestamp = self._pending_headers[body_id]
                    if (now - timestamp).total_seconds() > 30:
                        del self._pending_headers[body_id]
            threading.Event().wait(5)

    # Genera un identificador único para cada mensaje o archivo, asegurando
    # que no haya colisiones en las transferencias simultáneas y manteniendo
    # el valor dentro del rango de un byte.
    def _get_next_body_id(self):
        with self._body_id_lock:
            body_id = self._next_body_id
            self._next_body_id = (self._next_body_id + 1) % 256
            return body_id

    # Maneja el envío de datos y espera de confirmación con sistema de reintentos.
    # Es necesario para garantizar la entrega confiable de mensajes y headers,
    # implementando un mecanismo de reintento con espera exponencial.
    def _send_and_wait(self, data: bytes, recipient: bytes, timeout: float = 5.0, retries: int = 3):
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
                    
            if attempt < retries - 1:
                threading.Event().wait(0.5 * (attempt + 1))
                
        raise TimeoutError(f"No se recibió ACK de {recipient!r} después de {retries} intentos")

    # Envía un mensaje de texto a un peer específico, manejando el protocolo
    # de dos fases (header + body) y esperando confirmaciones. Es necesario
    # para garantizar la entrega confiable de mensajes de texto.
    def send(self, recipient: bytes, message: bytes, timeout: float = 5.0):
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
            self.discovery.discover_peers()
            raise

    # Envía un archivo a un peer específico usando TCP, con un protocolo de tres fases:
    # anuncio UDP, transferencia TCP y confirmación final. Es necesario para garantizar
    # la transferencia confiable de archivos grandes manteniendo el control del progreso.
    def send_file(self, recipient: bytes, file_bytes: bytes, filename: str, timeout: float = None):
        # Validación inicial del peer y obtención de su información
        info = self.discovery.get_peers().get(recipient)
        if not info:
            raise ValueError("Peer no encontrado en discovery")
            
        # Generación del ID único para este archivo
        body_id = self._get_next_body_id()
        print(f"Enviando archivo {filename} (body_id={body_id})")
        
        # Preparación del nombre del archivo para transmisión
        name_b = filename.encode('utf-8')
        if len(name_b) > 0xFFFF:
            raise ValueError("Nombre de archivo demasiado largo")
        name_len = len(name_b).to_bytes(2, 'big')
        
        # Construcción del cuerpo del mensaje según el protocolo:
        # [8 bytes body_id][2 bytes name_len][name_bytes][file_bytes]
        body = body_id.to_bytes(8, 'big') + name_len + name_b + file_bytes
        
        # Preparación del header UDP para anunciar la transferencia
        header = pack_header(
            user_from=self.user_id,
            user_to=recipient,
            op_code=OP_FILE,
            body_id=body_id,
            body_len=len(body)
        )
        
        try:
            # Fase 1: Envío del header UDP y espera de ACK
            self._send_and_wait(header, recipient, timeout or 5.0)
            print(f"Header UDP enviado, esperando ACK...")
            
            # Pequeña pausa para asegurar que el receptor esté listo
            time.sleep(0.5)
            
            # Fase 2: Transferencia TCP del archivo
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                # Configuración del socket TCP para mejor rendimiento
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB buffer
                sock.settimeout(timeout or 30.0)  # Timeout más largo para archivos grandes
                
                # Establecimiento de la conexión TCP
                print(f"Conectando a {info['ip']}:{TCP_PORT}...")
                sock.connect((info['ip'], TCP_PORT))
                
                # Envío del archivo en chunks para mejor manejo de memoria
                sent = 0
                chunk_size = 32768  # 32KB por chunk
                while sent < len(body):
                    chunk = body[sent:sent + chunk_size]
                    bytes_sent = sock.send(chunk)
                    if bytes_sent == 0:
                        raise ConnectionError("Conexión cerrada durante envío")
                    sent += bytes_sent
                    print(f"Enviados {sent}/{len(body)} bytes")
                
                # Fase 3: Espera del ACK final
                print("Esperando ACK final...")
                sock.shutdown(socket.SHUT_WR)  # Indicamos fin de transmisión
                
                # Configuración de timeout para el ACK final
                sock.settimeout(5.0)
                ack = sock.recv(RESPONSE_SIZE)
                if not ack or len(ack) != RESPONSE_SIZE:
                    raise ConnectionError(f"ACK inválido: recibidos {len(ack) if ack else 0} bytes")
                    
                try:
                    # Procesamiento del ACK final
                    resp = unpack_response(ack)
                    print(f"ACK recibido: status={resp['status']}, responder={resp['responder']!r}")
                    
                    # Manejo de diferentes estados de respuesta
                    if resp['status'] == RESP_OK:
                        print("Archivo enviado correctamente")
                    elif resp['status'] == 1:
                        print("El archivo ya existe en el destino")
                    elif resp['status'] == 2:
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

    # Envía un mensaje a todos los peers conocidos usando broadcast UDP.
    # Es necesario para comunicaciones globales que deben llegar a todos
    # los participantes del chat.
    def broadcast(self, message: bytes):
        # Preparación del header para broadcast UDP
        header = pack_header(
            user_from=self.user_id,
            user_to=BROADCAST_UID,
            op_code=OP_MESSAGE,
            body_id=self._get_next_body_id(),
            body_len=len(message)
        )
        # Envío a la dirección de broadcast de la red
        self.sock.sendto(header, ('255.255.255.255', UDP_PORT))

    # Envía un mensaje a todos los peers conocidos de forma individual.
    # Es necesario para garantizar la entrega confiable de mensajes a
    # múltiples destinatarios cuando el broadcast no es suficiente.
    def send_all(self, message: bytes):
        # Envío individual a cada peer conocido
        for peer in self.discovery.get_peers():
            try:
                self.send(peer, message)
            except Exception as e:
                print(f"Error enviando a {peer!r}: {e}")
                # Continuamos con el siguiente peer incluso si hay error

    # Inicia el bucle de recepción de mensajes TCP y UDP.
    # Es necesario para mantener el sistema de mensajería activo
    # y procesando comunicaciones entrantes.
    def start_listening(self):
        self.recv_loop()

    # Procesa los mensajes en la cola de forma asíncrona.
    # Es necesario para manejar los mensajes entrantes sin bloquear
    # el hilo principal de recepción.
    def _process_messages(self):
        while True:
            try:
                # Espera y procesamiento de mensajes de la cola
                msg = self._message_queue.get()
                if msg:
                    print(f"Procesando mensaje: {msg}")
            except Exception as e:
                print(f"Error procesando mensaje: {e}")

    # Bucle principal de recepción que maneja tanto mensajes UDP como
    # conexiones TCP entrantes. Es necesario para coordinar la recepción
    # de todos los tipos de comunicación soportados por el sistema.
    def recv_loop(self):
        # Iniciamos el hilo de aceptación TCP en paralelo
        tcp_thread = threading.Thread(
            target=self._tcp_accept_loop,
            name="TCPAcceptLoop",
            daemon=True
        )
        tcp_thread.start()

        # Bucle principal de recepción UDP
        while True:
            try:
                # Recepción de datos UDP
                data, addr = self.sock.recvfrom(HEADER_SIZE)
                
                # Procesamiento de headers LCP
                if len(data) == HEADER_SIZE:
                    try:
                        # Decodificación y validación del header
                        hdr = unpack_header(data)
                        print(f"Header recibido de {addr}: {hdr}")

                        # Verificación de destinatario
                        if hdr['user_to'] != self.user_id and hdr['user_to'] != BROADCAST_UID:
                            print(f"Ignorando mensaje para {hdr['user_to']!r}")
                            continue

                        # Evitamos procesar mensajes propios
                        if hdr['user_from'] == self.user_id:
                            print("Ignorando mensaje propio")
                            continue

                        # Envío de ACK al remitente
                        resp = pack_response(0, self.user_id)
                        self.sock.sendto(resp, addr)

                        # Si hay cuerpo pendiente, guardamos el header
                        if hdr['body_len'] > 0:
                            with self._pending_headers_lock:
                                self._pending_headers[hdr['body_id']] = (hdr, datetime.now(UTC))

                    except Exception as e:
                        print(f"Error procesando header: {e}")
                        continue

                # Procesamiento de respuestas (ACKs)
                elif len(data) == RESPONSE_SIZE:
                    try:
                        # Decodificación de la respuesta
                        resp = unpack_response(data)
                        key = resp['responder'].rstrip(b'\x00')
                        
                        # Notificación al hilo esperando el ACK
                        with self._acks_lock:
                            ev = self._acks.get(key)
                            if ev:
                                ev.set()
                    except Exception as e:
                        print(f"Error procesando respuesta: {e}")
                        continue

            except socket.timeout:
                continue  # Timeout normal, seguimos escuchando
            except Exception as e:
                print(f"Error en recv_loop: {e}")
                continue

    # Acepta conexiones TCP entrantes para transferencia de archivos.
    # Es necesario para manejar las conexiones de transferencia de archivos
    # de forma asíncrona sin bloquear el bucle principal de recepción.
    def _tcp_accept_loop(self):
        print("Iniciando bucle de aceptación TCP...")
        while True:
            try:
                # Aceptación de nuevas conexiones TCP
                sock, addr = self.tcp_sock.accept()
                print(f"Nueva conexión TCP desde {addr}")
                
                # Iniciamos un hilo dedicado para manejar la transferencia
                threading.Thread(
                    target=self._handle_tcp_file_transfer,
                    args=(sock, addr),
                    daemon=True
                ).start()
            except Exception as e:
                print(f"Error aceptando conexión TCP: {e}")

    # Maneja la transferencia de archivos por TCP, incluyendo la validación
    # del header, la recepción del archivo y el envío de confirmaciones.
    # Es necesario para garantizar la transferencia confiable de archivos
    # grandes y su correcta persistencia.
    def _handle_tcp_file_transfer(self, sock: socket.socket, addr):
        print(f"Manejando transferencia de archivo desde {addr}")
        sock.settimeout(30.0)  # Timeout extendido para archivos grandes

        # Función auxiliar para recibir exactamente n bytes
        def recv_exact(n):
            data = bytearray()
            while len(data) < n:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    raise ConnectionError("Conexión cerrada durante recepción")
                data.extend(chunk)
            return bytes(data)

        # Función auxiliar para detectar el tipo de archivo basado en firmas
        def detect_file_type(header_bytes):
            signatures = {
                b'\xFF\xD8\xFF': 'jpg',      # JPEG
                b'\x89\x50\x4E\x47': 'png',  # PNG
                b'\x47\x49\x46\x38': 'gif',  # GIF
                b'%PDF': 'pdf',              # PDF
                b'PK\x03\x04': 'zip'         # ZIP
            }
            for sig, ext in signatures.items():
                if header_bytes.startswith(sig):
                    return ext
            return None

        try:
            # Fase 1: Recepción y validación del ID del archivo
            file_id = int.from_bytes(recv_exact(8), 'big')
            print(f"ID de archivo recibido: {file_id}")

            # Búsqueda y validación del header correspondiente
            with self._pending_headers_lock:
                if file_id not in self._pending_headers:
                    print(f"No hay header pendiente para file_id={file_id}")
                    sock.send(pack_response(2, self.user_id))
                    return
                header, _ = self._pending_headers[file_id]
                del self._pending_headers[file_id]

            # Fase 2: Validación del remitente
            peer_ip = addr[0]
            peers = self.discovery.get_peers()
            sender = None
            for uid, info in peers.items():
                if info['ip'] == peer_ip:
                    sender = uid
                    break

            if not sender or sender != header['user_from']:
                print(f"Remitente no válido: {sender!r} != {header['user_from']!r}")
                sock.send(pack_response(2, self.user_id))
                return

            # Fase 3: Recepción del nombre del archivo
            name_len = int.from_bytes(recv_exact(2), 'big')
            if not 0 < name_len <= 0xFFFF:
                print(f"Longitud de nombre inválida: {name_len}")
                sock.send(pack_response(2, self.user_id))
                return

            filename = recv_exact(name_len).decode('utf-8')
            print(f"Nombre de archivo: {filename}")

            # Fase 4: Preparación para recepción del contenido
            remaining = header['body_len'] - 8 - 2 - name_len
            if remaining <= 0:
                print(f"Longitud de archivo inválida: {remaining}")
                sock.send(pack_response(2, self.user_id))
                return

            # Creación del directorio de descargas
            downloads = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Descargas")
            os.makedirs(downloads, exist_ok=True)

            # Detección del tipo de archivo y generación de nombre único
            base, ext = os.path.splitext(filename)
            if not ext and (peek := recv_exact(4)):
                detected = detect_file_type(peek)
                if detected:
                    ext = f".{detected}"
                remaining -= 4
            else:
                peek = b''

            # Generación de nombre único para evitar sobrescrituras
            counter = 0
            while True:
                test_name = f"{base}{f'_{counter}' if counter else ''}{ext}"
                full_path = os.path.join(downloads, test_name)
                if not os.path.exists(full_path):
                    break
                counter += 1

            # Fase 5: Recepción y escritura del archivo
            print(f"Guardando en {full_path}")
            with open(full_path, 'wb') as f:
                if peek:
                    f.write(peek)

                received = len(peek)
                while received < remaining:
                    chunk = sock.recv(min(32768, remaining - received))
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    print(f"Progreso: {received}/{remaining} bytes")

            # Fase 6: Validación y registro del archivo recibido
            if received == remaining:
                print("Archivo recibido completamente")
                sock.send(pack_response(0, self.user_id))

                # Registro en el historial
                self.history_store.append_file(
                    sender=header['user_from'],
                    recipient=self.user_id,
                    filename=os.path.basename(full_path),
                    timestamp=datetime.now(UTC)
                )
            else:
                print(f"Archivo incompleto: {received}/{remaining} bytes")
                sock.send(pack_response(2, self.user_id))
                try:
                    os.unlink(full_path)  # Eliminamos el archivo incompleto
                except:
                    pass

        except Exception as e:
            print(f"Error en transferencia: {e}")
            try:
                sock.send(pack_response(2, self.user_id))
            except:
                pass

        finally:
            try:
                sock.close()
            except:
                pass

    # Procesa mensajes y archivos recibidos, actualizando el historial
    # y manejando diferentes tipos de contenido. Es necesario para mantener
    # un registro consistente de todas las comunicaciones.
    def _handle_message_or_file(self, hdr, body: bytes):
        try:
            # Extracción del ID del mensaje y su contenido
            msg_id, content = unpack_message_body(body)
            
            # Procesamiento según el tipo de contenido
            if hdr['op_code'] == OP_MESSAGE:
                # Registro del mensaje en el historial
                self.history_store.append_message(
                    sender=hdr['user_from'],
                    recipient=hdr['user_to'],
                    message=content.decode('utf-8'),
                    timestamp=datetime.now(UTC)
                )
            
            elif hdr['op_code'] == OP_FILE:
                # Registro de la transferencia de archivo en el historial
                self.history_store.append_file(
                    sender=hdr['user_from'],
                    recipient=hdr['user_to'],
                    filename=content.decode('utf-8'),
                    timestamp=datetime.now(UTC)
                )
                
        except Exception as e:
            print(f"Error procesando mensaje/archivo: {e}")
