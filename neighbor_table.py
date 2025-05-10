

import threading
import time


NEIGHBOR_TTL = 15  

class NeighborTable:
    def __init__(self):
        # Diccionario: user_id 
        self._table = {}
        self._lock = threading.Lock()

        # Lanzar limpiador 
        cleaner = threading.Thread(target=self._cleanup_loop, daemon=True)
        cleaner.start()

    def add_neighbor(self, user_id: str, ip: str):
        """Agrega o actualiza la entrada de un vecino con timestamp actual."""
        with self._lock:
            self._table[user_id] = (ip, time.time())

    def remove_neighbor(self, user_id: str):
        """Elimina manualmente un vecino."""
        with self._lock:
            self._table.pop(user_id, None)

    def get_neighbors(self) -> dict:
        """
        Devuelve un snapshot de vecinos activos:
        { user_id: ip_address, … }
        """
        with self._lock:
            return {uid: info[0] for uid, info in self._table.items()}

    def _cleanup_loop(self):
        """Elimina entradas cuyo last_seen + TTL < ahora."""
        while True:
            now = time.time()
            with self._lock:
                expired = [uid for uid, (_, ts) in self._table.items()
                           if now - ts > NEIGHBOR_TTL]
                for uid in expired:
                    del self._table[uid]
            time.sleep(NEIGHBOR_TTL)

