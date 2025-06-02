# Implementa el mecanismo de descubrimiento de peers en red local mediante broadcasts UDP.
# Envía Echo-Requests, procesa respuestas y mantiene registro de peers activos.
# Filtra IPs locales para evitar auto-descubrimiento.

import socket
import time
import threading
from datetime import datetime, UTC
import ipaddress

from core.protocol import (
    UDP_PORT,
    BROADCAST_UID,
    pack_header,
    unpack_header,
    pack_response,
    unpack_response,
    HEADER_SIZE,
    RESPONSE_SIZE
)

# Umbral en segundos para considerar un peer desconectado
OFFLINE_THRESHOLD = 20.0

# Clase para el descubrimiento y seguimiento de peers en la red
# Gestiona registro de peers, comunicación UDP y persistencia
class Discovery:
    # Inicializa el sistema de descubrimiento de peers
    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0,
                 peers_store=None):
        # Prepara el ID de usuario (versión raw y padded)
        self.raw_id   = user_id.rstrip(b'\x00')
        self.user_id  = self.raw_id.ljust(20, b'\x00')
        self.broadcast_interval = broadcast_interval
        self.peers_store       = peers_store

        # Auto-detección de IP de interfaz activa 
        hostname = socket.gethostname()
        all_addrs = socket.gethostbyname_ex(hostname)[2]
        
        # Identifica IPs de interfaces WiFi y filtra loopback/link-local
        def is_probable_wifi_ip(ip):
            # Excluir loopback y link-local
            if ip.startswith('127.') or ip.startswith('169.254.'):
                return False
            # Identificar probables IPs WiFi (redes privadas típicas)
            return (ip.startswith('192.168.') or 
                    ip.startswith('10.') or 
                    (ip.startswith('172.') and 16 <= int(ip.split('.')[1]) <= 31))
        
        # Selección de IP principal para broadcast
        # Prioridad: IPs que parecen WiFi > otras no-loopback > primera disponible
        wifi_ips = [ip for ip in all_addrs if is_probable_wifi_ip(ip)]
        
        if wifi_ips:
            self.local_ip = wifi_ips[0]  # Tomamos la primera IP WiFi encontrada
        else:
            # Fallback a cualquier IP no-loopback
            self.local_ip = next((ip for ip in all_addrs if not ip.startswith("127.")), all_addrs[0])
            
        print(f"IP seleccionada para broadcast: {self.local_ip}")
        
        # Registro de todas las IPs locales incluyendo loopback
        # Esto es importante para filtrar auto-descubrimiento
        self.local_ips = set(all_addrs) | {"127.0.0.1"}

        # Mapa de peers conocidos con su información
        # Estructura: {padded_peer_id: {'ip': str, 'last_seen': datetime}}
        self.peers = {}

        # Configuración del socket UDP para broadcast
        # Habilitamos reuso de dirección y capacidad de broadcast
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # Intento de bind a la IP local seleccionada
        # Si falla, fallback a 0.0.0.0 (todas las interfaces)
        try:
            self.sock.bind((self.local_ip, UDP_PORT))
            print(f"Socket UDP vinculado a {self.local_ip}")
        except Exception as e:
            print(f"Error al vincular a {self.local_ip}, intentando con 0.0.0.0: {e}")
            self.sock.bind(('0.0.0.0', UDP_PORT))

        # Inicio de hilos de broadcast y persistencia
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        if self.peers_store:
            threading.Thread(target=self._persist_loop, daemon=True).start()

    # Obtiene información detallada de las interfaces de red
    # Esta función es importante para:
    # 1. Detectar todas las interfaces disponibles
    # 2. Obtener IPs y máscaras de red
    # 3. Manejar casos especiales de Windows
    def _get_network_interfaces(self):
        interfaces = []
        
        try:
            import subprocess
            import re
            
            # Ejecutar ipconfig con información detallada
            output = subprocess.check_output('ipconfig /all', shell=True).decode('latin1', errors='replace')
            
            current_if = None
            is_wifi = False
            
            for line in output.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Nueva interfaz detectada
                if not line.startswith(' '):
                    if current_if and current_if.get('ip'):
                        # Si es WiFi, marcarla como tal
                        if is_wifi:
                            current_if['is_wifi'] = True
                        interfaces.append(current_if)
                    
                    current_if = {'name': line, 'ip': None, 'mask': None, 'is_wifi': False, 'is_active': False}
                    is_wifi = 'wireless' in line.lower() or 'wi-fi' in line.lower() or 'wifi' in line.lower()
                    continue
                
                # Extracción de dirección IPv4
                if 'IPv4' in line and 'Address' in line:
                    try:
                        ip = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line)
                        if ip:
                            current_if['ip'] = ip.group(1)
                            current_if['is_active'] = True  # Si tiene IP, está activa
                    except Exception as e:
                        print(f"Error al extraer IP: {e}")
                
                # Extracción de máscara de subred
                if 'Subnet Mask' in line or 'Máscara de subred' in line:
                    try:
                        mask = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line)
                        if mask:
                            current_if['mask'] = mask.group(1)
                    except Exception as e:
                        print(f"Error al extraer máscara: {e}")
                
                # Identificar si es una conexión WiFi
                if 'wireless' in line.lower() or 'wi-fi' in line.lower() or 'wifi' in line.lower():
                    is_wifi = True
            
            # Añadir la última interfaz si existe y tiene IP
            if current_if and current_if.get('ip'):
                if is_wifi:
                    current_if['is_wifi'] = True
                interfaces.append(current_if)
            
            # Imprimir información de depuración sobre interfaces detectadas
            print(f"Interfaces detectadas: {len(interfaces)}")
            for iface in interfaces:
                status = "Activo" if iface.get('is_active') else "Inactivo"
                wifi = "WiFi" if iface.get('is_wifi') else "Cable/Otro"
                print(f"- {iface.get('name')}: {iface.get('ip')} ({wifi}, {status})")
                
        except Exception as e:
            print(f"Error obteniendo interfaces: {e}")
            
        return interfaces

    # Bucle principal de broadcast
    # Envía Echo-Request periódicamente según broadcast_interval
    def _broadcast_loop(self):
        while True:
            self._do_broadcast()
            time.sleep(self.broadcast_interval)

    # Realiza el envío de un Echo-Request por broadcast
    # Esta función mejorada:
    # 1. Empaqueta el mensaje según el protocolo
    # 2. Intenta usar la dirección de broadcast específica de la subred
    # 3. Registra la actividad para debugging y maneja errores
    def _do_broadcast(self):
        pkt = pack_header(
            user_from=self.user_id,
            user_to=BROADCAST_UID,
            op_code=0
        )
        
        try:
            # Determinamos la dirección de broadcast más adecuada
            broadcast_addresses = ['255.255.255.255']  # Dirección de broadcast general
            
            # Intentar determinar la dirección de broadcast específica para esta subred
            try:
                # Obtener interfaces de red y encontrar la activa que corresponda a nuestra IP
                ifaces = self._get_network_interfaces()
                for iface in ifaces:
                    if iface.get('ip') == self.local_ip and iface.get('mask'):
                        # Calcular dirección de broadcast específica para esta subred
                        ip = ipaddress.IPv4Address(iface.get('ip'))
                        mask = ipaddress.IPv4Address(iface.get('mask'))
                        # Operación para obtener dirección de broadcast: (IP OR (NOT Mask))
                        ip_int = int(ip)
                        mask_int = int(mask)
                        broadcast_int = ip_int | (~mask_int & 0xFFFFFFFF)
                        specific_broadcast = str(ipaddress.IPv4Address(broadcast_int))
                        broadcast_addresses.insert(0, specific_broadcast)
                        print(f"Usando broadcast específico para subred: {specific_broadcast}")
                        break
            except Exception as e:
                print(f"Error calculando broadcast específico: {e}")
            
            # Intentar broadcast con cada dirección, empezando por la más específica
            sent = False
            errors = []
            
            for addr in broadcast_addresses:
                try:
                    self.sock.sendto(pkt, (addr, UDP_PORT))
                    print(f"Broadcast enviado a {addr} desde {self.local_ip} con ID {self.raw_id}")
                    sent = True
                    break  # Si funciona con una dirección, no intentamos más
                except Exception as e:
                    errors.append(f"{addr}: {str(e)}")
            
            if not sent:
                print(f"No se pudo enviar broadcast a ninguna dirección. Errores: {errors}")
                
        except Exception as e:
            print(f"Error al preparar broadcast: {e}")

    # Fuerza descubrimiento inmediato de peers
    def force_discover(self):
        self._do_broadcast()

    # Actualiza periódicamente el estado de peers y persiste la información
    # Filtra IPs locales y actualiza estados conectado/desconectado
    def _persist_loop(self):
        while True:
            time.sleep(5)
            now = datetime.now(UTC)
            to_save = {}
            for uid, info in self.peers.items():
                ip = info['ip']
                if ip in self.local_ips:
                    continue
                age = (now - info['last_seen']).total_seconds()
                status = 'connected' if age < OFFLINE_THRESHOLD else 'disconnected'
                
                # Conversión de identificador para almacenamiento
                key = uid.decode('utf-8', errors='ignore') if isinstance(uid, bytes) else uid
                
                to_save[key] = {
                    'ip':         ip,
                    'last_seen':  info['last_seen'],
                    'status':     status
                }
            try:
                self.peers_store.save(to_save)
            except Exception as e:
                print(f"Error guardando peers: {e}")

    # Procesa Echo-Request y responde al remitente
    # Filtra auto-mensajes y actualiza registro de peers
    def handle_echo(self, data: bytes, addr):
        try:
            hdr      = unpack_header(data[:HEADER_SIZE])
            raw_id   = hdr['user_from']                    # ID sin padding
            raw_peer = raw_id.ljust(20, b'\x00')           # ID con padding
            peer_ip  = addr[0]

            print(f"Echo recibido de {peer_ip} con ID {raw_id}")

            # Evita auto-descubrimiento
            if peer_ip in self.local_ips or raw_id == self.raw_id:
                print(f"Ignorando echo de IP local o self: {peer_ip}")
                return

            # Envía respuesta
            try:
                resp = pack_response(0, self.user_id)
                self.sock.sendto(resp, addr)
                print(f"Respuesta echo enviada a {peer_ip}")
            except Exception as e:
                print(f"Error al enviar respuesta echo: {e}")
                return

            # Limpia registros antiguos con misma IP
            for uid in list(self.peers):
                if self.peers[uid]['ip'] == peer_ip and uid != raw_peer:
                    del self.peers[uid]

            # Actualización del mapa de peers
            self.peers[raw_peer] = {
                'ip':        peer_ip,
                'last_seen': datetime.now(UTC)
            }
            print(f"Peer actualizado: {peer_ip}")
        except Exception as e:
            print(f"Error procesando echo: {e}")

    # Procesa Echo-Reply recibido y actualiza el mapa de peers
    def handle_response(self, data: bytes, addr):
        try:
            resp     = unpack_response(data[:RESPONSE_SIZE])
            resp_id  = resp['responder']                   # ID sin padding
            raw_peer = resp_id.ljust(20, b'\x00')          # ID con padding
            peer_ip  = addr[0]

            print(f"Respuesta recibida de {peer_ip} con ID {resp_id}")

            # Filtra respuestas inválidas o propias
            if resp['status'] != 0 or peer_ip in self.local_ips or resp_id == self.raw_id:
                print(f"Ignorando respuesta de IP local o self: {peer_ip}")
                return

            # Limpia registros antiguos con misma IP
            for uid in list(self.peers):
                if self.peers[uid]['ip'] == peer_ip and uid != raw_peer:
                    del self.peers[uid]

            # Actualiza registro de peer
            self.peers[raw_peer] = {
                'ip':        peer_ip,
                'last_seen': datetime.now(UTC)
            }
            print(f"Peer actualizado desde respuesta: {peer_ip}")
        except Exception as e:
            print(f"Error procesando respuesta: {e}")

    # Retorna mapa filtrado de peers activos (excluye IPs locales)
    def get_peers(self) -> dict:
        return {
            uid: info
            for uid, info in self.peers.items()
            if info['ip'] not in self.local_ips
        }
