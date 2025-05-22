# core/engine.py

import threading
from datetime import datetime
import os
import sys

# Asegurarnos de que el proyecto raíz esté en sys.path
# de modo que `import persistence` y `import core` funcione cuando se
# llame `streamlit run ui/interface.py`
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
    Se arranca automáticamente desde Streamlit.
    """

    def __init__(self,
                 user_id: bytes,
                 broadcast_interval: float = 1.0):
        # Normalizar user_id a 20 bytes
        if isinstance(user_id, str):
            user_id = user_id.encode('utf-8')
        self.user_id = user_id.ljust(20, b'\x00')[:20]

        # --- Persistencia ---
        # Los JSON se almacenarán en persistence/peers.json y persistence/history.json
        self.peers_store = PeersStore()      # peers.json en la misma carpeta persistence/
        self.history_store = HistoryStore()  # history.json en persistence/

        # Cargar peers previos (si existen) para no perder histórica
        loaded = self.peers_store.load()
        # Discovery arrancará vacío, luego volcamos los cargados
        # (se mantendrán hasta que llegue un broadcast real)
        # loaded: dict[bytes] → {'ip': str, 'last_seen': datetime}
        # Hacemos shallow copy para no exponer internals accidentales
        initial_peers = loaded.copy()

        # --- Core Discovery ---
        # Broadcast continuo + recv_loop + persistencia automática
        self.discovery = Discovery(
            user_id=self.user_id,
            broadcast_interval=broadcast_interval,
            peers_store=self.peers_store
        )
        # Incorporar peers cargados antes de que Discovery empiece a escuchar nuevos
        # (de esta forma no "desaparecen" hasta recibir un nuevo broadcast)
        self.discovery.peers.update(initial_peers)

        # --- Core Messaging ---
        # Usa el mismo socket de Discovery para enviar/recibir mensajes
        self.messaging = Messaging(
            user_id=self.user_id,
            discovery=self.discovery,
            history_store=self.history_store
        )

    def start(self):
        """
        Arranca el loop de recepción de mensajes en background.
        Discovery ya inició sus hilos en el constructor.
        """
        recv_thread = threading.Thread(
            target=self.messaging.recv_loop,
            name="MessagingRecvLoop",
            daemon=True
        )
        recv_thread.start()
