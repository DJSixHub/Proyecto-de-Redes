# Motor principal que orquesta todos los componentes del sistema
# Coordina descubrimiento de peers, mensajería y persistencia
# Gestiona información de peers y ciclo de vida de los hilos

import threading
import os
import sys

# Configuración del path para importaciones
# Aseguramos que el directorio raíz del proyecto esté disponible para imports
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.discovery import Discovery
from core.messaging import Messaging
from persistence.peers_store import PeersStore
from persistence.history_store import HistoryStore

# Coordina todos los componentes del sistema
# Gestiona módulos, persistencia y ciclo de vida de hilos
class Engine:
    # Inicializa el motor con identificador de usuario e intervalo de broadcast
    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0):
        # Normalización del identificador de usuario
        # Aseguramos que tenga exactamente 20 bytes con padding
        if isinstance(user_id, str):
            user_id = user_id.encode('utf-8')
        raw_id = user_id
        self.user_id = raw_id.ljust(20, b'\x00')[:20]

        # Inicialización de los componentes de persistencia
        # Estos manejan el almacenamiento de peers y historial
        self.peers_store = PeersStore()      # Almacena información de peers
        self.history_store = HistoryStore()  # Almacena historial de mensajes

        # Configuración del módulo de descubrimiento
        # Este componente maneja la detección de peers en la red
        self.discovery = Discovery(
            user_id=self.user_id,
            broadcast_interval=broadcast_interval,
            peers_store=self.peers_store
        )

        # Carga y filtrado de peers previos
        # Eliminamos peers con la misma IP local para evitar auto-conexiones
        loaded = self.peers_store.load()  # Diccionario de {uid_bytes: {'ip', 'last_seen'}}
        local_ip = self.discovery.local_ip
        filtered = {
            uid: info
            for uid, info in loaded.items()
            if info['ip'] != local_ip  # Excluimos peers con nuestra misma IP
        }
        self.discovery.peers.update(filtered)

        # Configuración del módulo de mensajería
        # Este componente maneja el envío y recepción de mensajes
        self.messaging = Messaging(
            user_id=self.user_id,
            discovery=self.discovery,
            history_store=self.history_store
        )

    # Inicia el hilo de recepción de mensajes
    # Esta función es importante porque:
    # 1. Crea un hilo dedicado para la recepción
    # 2. Configura el hilo como daemon para limpieza automática
    # 3. Mantiene la aplicación escuchando mensajes continuamente
    def start(self):
        recv_thread = threading.Thread(
            target=self.messaging.recv_loop,
            name="MessagingRecvLoop",
            daemon=True  # El hilo se cerrará cuando el programa principal termine
        )
        recv_thread.start()
