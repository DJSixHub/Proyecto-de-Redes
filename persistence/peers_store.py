# persistence/peers_store.py

import os
import json
from datetime import datetime

class PeersStore:
    """
    Guarda y carga el mapa de peers en formato JSON dentro de esta carpeta.
    """

    def __init__(self, filename: str = "peers.json"):
        # Carpeta de este módulo
        folder = os.path.dirname(os.path.abspath(__file__))
        # Nombre del fichero en esta carpeta
        self.path = os.path.join(folder, os.path.basename(filename))
        os.makedirs(folder, exist_ok=True)

    def save(self, peers: dict):
        serial = {}
        for uid, info in peers.items():
            uid_str = uid.decode('utf-8')
            serial[uid_str] = {
                'ip': info['ip'],
                'last_seen': info['last_seen'].isoformat()
            }
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(serial, f, ensure_ascii=False, indent=2)

    def load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        result = {}
        for uid_str, info in data.items():
            result[uid_str.encode('utf-8')] = {
                'ip': info['ip'],
                'last_seen': datetime.fromisoformat(info['last_seen'])
            }
        return result
