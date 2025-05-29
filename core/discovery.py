# core/discovery.py

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

# Este archivo implementa el sistema de descubrimiento de peers en la red local. El flujo
# comienza con la inicialización del sistema que identifica las interfaces de red locales,
# luego inicia un ciclo de broadcast periódico para anunciar su presencia y descubrir otros
# peers. El sistema mantiene un registro actualizado de los peers activos, filtra
# automáticamente las IPs locales para evitar auto-descubrimiento, y persiste el estado
# de los peers para mantener un historial de conexiones. También maneja el procesamiento
# de solicitudes y respuestas de eco para mantener el estado de la red actualizado.

OFFLINE_THRESHOLD = 20.0  # segundos antes de considerar un peer desconectado

class Discovery:
    # Clase principal que gestiona el descubrimiento y seguimiento de peers en la red.
    # Mantiene un mapa actualizado de peers activos, maneja la comunicación UDP para
    # descubrimiento y proporciona información sobre las interfaces de red locales.
    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0,
                 peers_store=None):
        # Normalización del ID de usuario
        self.raw_id   = user_id.rstrip(b'\x00')
        self.user_id  = self.raw_id.ljust(20, b'\x00')
        self.broadcast_interval = broadcast_interval
        self.peers_store       = peers_store

        # Detección de la interfaz de red más adecuada
        hostname  = socket.gethostname()
        all_addrs = socket.gethostbyname_ex(hostname)[2]
        
        # Preferimos interfaces en la red 192.168.1.x, luego cualquier no-loopback
        self.local_ip = next(
            (ip for ip in all_addrs if ip.startswith("192.168.1.")),
            next((ip for ip in all_addrs if not ip.startswith("127.")), all_addrs[0])
        )
        print(f"IP seleccionada para broadcast: {self.local_ip}")
        
        # Registro de todas las IPs locales para filtrado
        self.local_ips = set(all_addrs) | {"127.0.0.1"}

        # Mapa de peers conocidos: uid -> {ip, last_seen}
        self.peers = {}

        # Configuración del socket UDP para broadcast
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # Intentamos vincular a la IP local específica, con fallback a 0.0.0.0
        try:
            self.sock.bind((self.local_ip, UDP_PORT))
            print(f"Socket UDP vinculado a {self.local_ip}")
        except Exception as e:
            print(f"Error al vincular a {self.local_ip}, intentando con 0.0.0.0: {e}")
            self.sock.bind(('0.0.0.0', UDP_PORT))

        # Iniciamos hilos de mantenimiento
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        if self.peers_store:
            threading.Thread(target=self._persist_loop, daemon=True).start()

    # Obtiene información detallada sobre todas las interfaces de red del sistema,
    # incluyendo sus direcciones IP y máscaras. Es necesario para identificar
    # correctamente las interfaces locales.
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

    # Ejecuta el ciclo principal de broadcast que periódicamente anuncia
    # la presencia del peer en la red.
    def _broadcast_loop(self):
        while True:
            self._do_broadcast()
            time.sleep(self.broadcast_interval)

    # Envía un paquete de Echo-Request a la dirección de broadcast para
    # descubrir otros peers en la red.
    def _do_broadcast(self):
        pkt = pack_header(
            user_from=self.user_id,
            user_to=BROADCAST_UID,
            op_code=0
        )
        try:
            self.sock.sendto(pkt, ('255.255.255.255', UDP_PORT))
            print(f"Broadcast enviado desde {self.local_ip} con ID {self.raw_id}")
        except Exception as e:
            print(f"Error al enviar broadcast: {e}")

    # Fuerza un descubrimiento inmediato enviando un broadcast,
    # útil cuando se necesita actualizar la lista de peers rápidamente.
    def force_discover(self):
        self._do_broadcast()

    # Ejecuta el ciclo de persistencia que guarda periódicamente el estado
    # de los peers conocidos, filtrando las IPs locales y actualizando
    # su estado de conexión.
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

    # Procesa las solicitudes de Echo-Request recibidas, validando el origen,
    # respondiendo con un Echo-Reply y actualizando el registro de peers.
    def handle_echo(self, data: bytes, addr):
        try:
            hdr      = unpack_header(data[:HEADER_SIZE])
            raw_id   = hdr['user_from']
            raw_peer = raw_id.ljust(20, b'\x00')
            peer_ip  = addr[0]

            print(f"Echo recibido de {peer_ip} con ID {raw_id}")

            if peer_ip in self.local_ips or raw_id == self.raw_id:
                print(f"Ignorando echo de IP local o self: {peer_ip}")
                return

            try:
                resp = pack_response(0, self.user_id)
                self.sock.sendto(resp, addr)
                print(f"Respuesta echo enviada a {peer_ip}")
            except Exception as e:
                print(f"Error al enviar respuesta echo: {e}")
                return

            for uid in list(self.peers):
                if self.peers[uid]['ip'] == peer_ip and uid != raw_peer:
                    del self.peers[uid]

            self.peers[raw_peer] = {
                'ip':        peer_ip,
                'last_seen': datetime.now(UTC)
            }
            print(f"Peer actualizado: {peer_ip}")
        except Exception as e:
            print(f"Error procesando echo: {e}")

    # Procesa las respuestas de Echo-Reply recibidas, validando el origen
    # y actualizando el registro de peers con la información recibida.
    def handle_response(self, data: bytes, addr):
        try:
            resp     = unpack_response(data[:RESPONSE_SIZE])
            resp_id  = resp['responder']
            raw_peer = resp_id.ljust(20, b'\x00')
            peer_ip  = addr[0]

            print(f"Respuesta recibida de {peer_ip} con ID {resp_id}")

            if resp['status'] != 0 or peer_ip in self.local_ips or resp_id == self.raw_id:
                print(f"Ignorando respuesta de IP local o self: {peer_ip}")
                return

            for uid in list(self.peers):
                if self.peers[uid]['ip'] == peer_ip and uid != raw_peer:
                    del self.peers[uid]

            self.peers[raw_peer] = {
                'ip':        peer_ip,
                'last_seen': datetime.now(UTC)
            }
            print(f"Peer actualizado desde respuesta: {peer_ip}")
        except Exception as e:
            print(f"Error procesando respuesta: {e}")

    # Obtiene la lista filtrada de peers conocidos, excluyendo aquellos
    # con IPs locales para evitar auto-referencias.
    def get_peers(self) -> dict:
        return {
            uid: info
            for uid, info in self.peers.items()
            if info['ip'] not in self.local_ips
        }
