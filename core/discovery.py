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

OFFLINE_THRESHOLD = 20.0  # segundos antes de considerar un peer desconectado

class Discovery:
    """
    Envía Echo-Request periódicos y mantiene el mapa de peers.
    Filtra automáticamente cualquier IP local de la máquina.
    Expone `local_ip` (IP principal) y `local_ips` (conjunto de todas las locales).
    """

    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0,
                 peers_store=None):
        # UID raw (sin padding) y padded (20 bytes)
        self.raw_id   = user_id.rstrip(b'\x00')
        self.user_id  = self.raw_id.ljust(20, b'\x00')
        self.broadcast_interval = broadcast_interval
        self.peers_store       = peers_store

        # Determinar IP principal y todas las IPs locales
        hostname  = socket.gethostname()
        all_addrs = socket.gethostbyname_ex(hostname)[2]
        
        # Primero intentar encontrar una IP en la subred 192.168.1.x
        self.local_ip = next(
            (ip for ip in all_addrs if ip.startswith("192.168.1.")),
            next((ip for ip in all_addrs if not ip.startswith("127.")), all_addrs[0])
        )
        print(f"IP seleccionada para broadcast: {self.local_ip}")
        
        # Conjunto de todas las IPs de la máquina, incluyendo loopback
        self.local_ips = set(all_addrs) | {"127.0.0.1"}

        # Mapa interno: padded_peer_id (20 bytes) → {'ip', 'last_seen'}
        self.peers = {}

        # Socket UDP en todas las interfaces
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # Hacer bind específicamente a la IP local que queremos usar
        try:
            self.sock.bind((self.local_ip, UDP_PORT))
            print(f"Socket UDP vinculado a {self.local_ip}")
        except Exception as e:
            print(f"Error al vincular a {self.local_ip}, intentando con 0.0.0.0: {e}")
            self.sock.bind(('0.0.0.0', UDP_PORT))

        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        if self.peers_store:
            threading.Thread(target=self._persist_loop, daemon=True).start()

    def _get_network_interfaces(self):
        """Obtiene todas las interfaces de red con sus IPs y máscaras"""
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

    def _broadcast_loop(self):
        while True:
            self._do_broadcast()
            time.sleep(self.broadcast_interval)

    def _do_broadcast(self):
        """Envía un Echo-Request (op_code=0) a la dirección de broadcast."""
        pkt = pack_header(
            user_from=self.user_id,
            user_to=BROADCAST_UID,
            op_code=0
        )
        try:
            # Enviar a la dirección de broadcast desde la IP local específica
            self.sock.sendto(pkt, ('255.255.255.255', UDP_PORT))
            print(f"Broadcast enviado desde {self.local_ip} con ID {self.raw_id}")
        except Exception as e:
            print(f"Error al enviar broadcast: {e}")

    def force_discover(self):
        """Envía inmediatamente un broadcast de descubrimiento."""
        self._do_broadcast()

    def _persist_loop(self):
        """
        Cada 5s, filtra cualquier peer cuya IP sea local
        y persiste el resto con su estado conectado/disconnected.
        """
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
                
                # Si uid es bytes, convertirlo a string, si ya es string usarlo directamente
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

    def handle_echo(self, data: bytes, addr):
        """
        Procesa un Echo-Request (op_code=0):
        - Ignora si la IP es local o el UID es el propio.
        - Responde Echo-Reply.
        - Registra o actualiza el peer, eliminando antiguos UID de la misma IP.
        """
        try:
            hdr      = unpack_header(data[:HEADER_SIZE])
            raw_id   = hdr['user_from']                    # bytes sin padding
            raw_peer = raw_id.ljust(20, b'\x00')           # padded 20 bytes
            peer_ip  = addr[0]

            print(f"Echo recibido de {peer_ip} con ID {raw_id}")

            # Para evitar descubrirnos a nosotros mismos comparamos el trimmed
            if peer_ip in self.local_ips or raw_id == self.raw_id:
                print(f"Ignorando echo de IP local o self: {peer_ip}")
                return

            # Responder con Echo-Reply
            try:
                resp = pack_response(0, self.user_id)
                self.sock.sendto(resp, addr)
                print(f"Respuesta echo enviada a {peer_ip}")
            except Exception as e:
                print(f"Error al enviar respuesta echo: {e}")
                return

            # Eliminar UID previos para esta IP
            for uid in list(self.peers):
                if self.peers[uid]['ip'] == peer_ip and uid != raw_peer:
                    del self.peers[uid]

            # Registrar/actualizar
            self.peers[raw_peer] = {
                'ip':        peer_ip,
                'last_seen': datetime.now(UTC)
            }
            print(f"Peer actualizado: {peer_ip}")
        except Exception as e:
            print(f"Error procesando echo: {e}")

    def handle_response(self, data: bytes, addr):
        """
        Procesa un Echo-Reply (RESPONSE_FMT):
        - Igual que handle_echo, pero desempaquetando RESPONSE_FMT.
        """
        try:
            resp     = unpack_response(data[:RESPONSE_SIZE])
            resp_id  = resp['responder']                   # bytes sin padding
            raw_peer = resp_id.ljust(20, b'\x00')          # padded 20 bytes
            peer_ip  = addr[0]

            print(f"Respuesta recibida de {peer_ip} con ID {resp_id}")

            # Comparamos trimmed para saltarnos nuestro propio id
            if resp['status'] != 0 or peer_ip in self.local_ips or resp_id == self.raw_id:
                print(f"Ignorando respuesta de IP local o self: {peer_ip}")
                return

            # Eliminar UID previos para esta IP
            for uid in list(self.peers):
                if self.peers[uid]['ip'] == peer_ip and uid != raw_peer:
                    del self.peers[uid]

            # Registrar/actualizar
            self.peers[raw_peer] = {
                'ip':        peer_ip,
                'last_seen': datetime.now(UTC)
            }
            print(f"Peer actualizado desde respuesta: {peer_ip}")
        except Exception as e:
            print(f"Error procesando respuesta: {e}")

    def get_peers(self) -> dict:
        """
        Devuelve solo peers cuya IP no sea local,
        con su last_seen actualizado.
        """
        return {
            uid: info
            for uid, info in self.peers.items()
            if info['ip'] not in self.local_ips
        }
