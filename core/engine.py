# core/engine.py

import threading
import os
import sys

# Asegurar que PROJECT_ROOT esté en sys.path para importaciones relativas
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.discovery import Discovery
from core.messaging import Messaging
from persistence.peers_store import PeersStore
from persistence.history_store import HistoryStore


class Engine:
    """
    Orquesta Discovery, Messaging y persistencia.
    Limpia automáticamente peers.json al arranque para:
      - Eliminar entradas con IP local
      - Quitar duplicados de misma IP, conservando el más reciente
    """

    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0):
        # Normalizar user_id a bytes y 20 bytes de longitud
        if isinstance(user_id, str):
            user_id = user_id.encode('utf-8')
        raw_id = user_id
        self.user_id = raw_id.ljust(20, b'\x00')[:20]

        # --- Persistencia ---
        self.peers_store = PeersStore()      # persistence/peers.json
        self.history_store = HistoryStore()  # persistence/history.json

        # --- Discovery ---
        # Primero instanciar Discovery para obtener local_ips
        self.discovery = Discovery(
            user_id=self.user_id,
            broadcast_interval=broadcast_interval,
            peers_store=self.peers_store
        )

        # Limpieza automática de peers.json
        self.peers_store.clean(local_ips=self.discovery.local_ips)

        # Cargar peers limpios (ya sin IPs locales ni duplicados)
        loaded = self.peers_store.load()  # { uid_bytes: info }

        # Inyectar en memoria
        self.discovery.peers.update(loaded)

        # --- Mensajería ---
        self.messaging = Messaging(
            user_id=self.user_id,
            discovery=self.discovery,
            history_store=self.history_store
        )

    def start(self):
        """
        Arranca el loop de recepción de mensajes.
        Discovery ya inició broadcast y persistencia en su constructor.
        """
        recv_thread = threading.Thread(
            target=self.messaging.recv_loop,
            name="MessagingRecvLoop",
            daemon=True
        )
        recv_thread.start()
