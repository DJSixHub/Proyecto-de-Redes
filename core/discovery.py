# Mecanismo de descubrimiento de peers mediante broadcasts UDP
# Envía Echo-Requests, procesa respuestas y mantiene registro de peers
# Filtra IPs locales para prevenir auto-descubrimiento

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
from util import get_local_ip_and_broadcast

# Umbral para considerar un peer desconectado (segundos)
OFFLINE_THRESHOLD = 20.0

# Gestiona descubrimiento y seguimiento de peers en la red
# Registra peers activos y maneja comunicación UDP
class Discovery:
    # Inicializa sistema de descubrimiento con ID de usuario
    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0,
                 peers_store=None):
        # Prepara ID: versión raw y con padding
        self.raw_id   = user_id.rstrip(b'\x00')
        self.user_id  = self.raw_id.ljust(20, b'\x00')
        self.broadcast_interval = broadcast_interval
        self.peers_store       = peers_store

        # Detección de IP y dirección broadcast
        try:
            self.local_ip, self.broadcast_addr = get_local_ip_and_broadcast()
            print(f"IP seleccionada para broadcast: {self.local_ip}")
            print(f"Dirección de broadcast: {self.broadcast_addr}")
            
            # IPs locales para filtrado
            hostname = socket.gethostname()
            self.local_ips = set(socket.gethostbyname_ex(hostname)[2]) | {"127.0.0.1"}
            
        except RuntimeError as e:
            print(f"Error detectando red: {e}")
            # Configuración fallback
            self.local_ip = "127.0.0.1"
            self.broadcast_addr = "255.255.255.255"
            self.local_ips = {"127.0.0.1"}

        # Mapa de peers: {id_con_padding: {'ip': str, 'last_seen': datetime}}
        self.peers = {}

        # Socket UDP para broadcast
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # Intento de bind a la IP local seleccionada
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

    # Obtiene información de interfaces de red disponibles
    # Extrae IPs y máscaras de red usando ipconfig
    def _get_network_interfaces(self):
        interfaces = []
        
        try:
            import subprocess
            output = subprocess.check_output('ipconfig /all', shell=True).decode('latin1')
            
            current_if = None
            for line in output.split('\n'):
                line = line.strip()
                
                if not line:
                    continue
                    
                if not line.startswith(' '):
                    current_if = {'name': line, 'ip': None, 'mask': None}
                    continue
                    
                if 'IPv4' in line and 'Address' in line:
                    try:
                        current_if['ip'] = line.split(':')[-1].strip()
                        interfaces.append(current_if)
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error obteniendo interfaces: {e}")
            
        return interfaces

    # Envía broadcasts periódicos según intervalo configurado
    def _broadcast_loop(self):
        while True:
            self._do_broadcast()
            time.sleep(self.broadcast_interval)

    # Envía un Echo-Request por broadcast
    # Empaqueta mensaje y maneja errores
    def _do_broadcast(self):
        pkt = pack_header(
            user_from=self.user_id,
            user_to=BROADCAST_UID,
            op_code=0
        )
        try:
            # Broadcast usando la dirección detectada
            self.sock.sendto(pkt, (self.broadcast_addr, UDP_PORT))
            print(f"Broadcast enviado desde {self.local_ip} con ID {self.raw_id}")
        except Exception as e:
            print(f"Error al enviar broadcast: {e}")

    # Fuerza broadcast inmediato
    def force_discover(self):
        self._do_broadcast()

    # Actualiza y persiste información de peers periódicamente
    # Filtra peers locales y actualiza estados conectado/desconectado
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

    # Procesa Echo-Request y responde al peer
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

    # Procesa Echo-Reply y actualiza registro de peers
    # Verifica validez de la respuesta y filtra auto-respuestas
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

    # Retorna mapa de peers activos excluyendo IPs locales
    def get_peers(self) -> dict:
        return {
            uid: info
            for uid, info in self.peers.items()
            if info['ip'] not in self.local_ips
        }