# core/engine.py

import threading
import os
import sys

# Este archivo implementa el motor principal del sistema de chat, orquestando todos los componentes.
# El flujo comienza con la inicialización del motor que coordina el descubrimiento de peers,
# la mensajería y la persistencia de datos. Primero, configura el ID del usuario y los almacenes
# de datos persistentes, luego inicializa el sistema de descubrimiento filtrando peers locales,
# y finalmente configura el sistema de mensajería. El motor actúa como punto central de control,
# gestionando el ciclo de vida de los componentes y sus interacciones.

# Asegurar que PROJECT_ROOT esté en sys.path para importaciones relativas
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.discovery import Discovery
from core.messaging import Messaging
from persistence.peers_store import PeersStore
from persistence.history_store import HistoryStore


class Engine:
    # Clase principal que orquesta todos los componentes del sistema de chat.
    # Coordina el descubrimiento de peers, la mensajería y la persistencia,
    # asegurando que todos los componentes trabajen juntos de manera coherente.
    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0):
        # Normalizar user_id a 20 bytes
        if isinstance(user_id, str):
            user_id = user_id.encode('utf-8')
        raw_id = user_id
        self.user_id = raw_id.ljust(20, b'\x00')[:20]

        # Persistencia
        self.peers_store = PeersStore()      # persistence/peers.json
        self.history_store = HistoryStore()  # persistence/history.json

        # Discovery (broadcast periódico y persistencia)
        self.discovery = Discovery(
            user_id=self.user_id,
            broadcast_interval=broadcast_interval,
            peers_store=self.peers_store
        )

        # Cargar peers previos y filtrar la IP local
        loaded = self.peers_store.load()  # { uid_bytes: {'ip', 'last_seen'} }
        local_ip = self.discovery.local_ip
        filtered = {
            uid: info
            for uid, info in loaded.items()
            if info['ip'] != local_ip
        }
        self.discovery.peers.update(filtered)

        # Mensajería
        self.messaging = Messaging(
            user_id=self.user_id,
            discovery=self.discovery,
            history_store=self.history_store
        )

    # Inicia el sistema de mensajería en un hilo separado, permitiendo la
    # recepción asíncrona de mensajes mientras el sistema de descubrimiento
    # ya está ejecutándose desde su inicialización.
    def start(self):
        """
        Arranca el hilo de recepción de mensajes.
        Discovery ya inició broadcast y persistencia en su constructor.
        """
        recv_thread = threading.Thread(
            target=self.messaging.recv_loop,
            name="MessagingRecvLoop",
            daemon=True
        )
        recv_thread.start()
