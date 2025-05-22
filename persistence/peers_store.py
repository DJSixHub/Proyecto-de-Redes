# persistence/peers_store.py

import os
import json
from datetime import datetime
from typing import Dict, Any

class PeersStore:
    """
    Guarda y carga peers con ip, last_seen e status.
    """

    def __init__(self, filename: str = "peers.json"):
        folder = os.path.dirname(os.path.abspath(__file__))
        self.path = os.path.join(folder, filename)
        os.makedirs(folder, exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump({}, f)

    def save(self, peers: Dict[bytes, Dict[str, Any]]):
        """
        peers: raw_uid bytes → {'ip': str, 'last_seen': datetime, 'status': str}
        """
        serial = {}
        for uid, info in peers.items():
            key = uid.decode('utf-8')
            serial[key] = {
                'ip': info['ip'],
                'last_seen': info['last_seen'].isoformat(),
                'status': info['status']
            }
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(serial, f, ensure_ascii=False, indent=2)

    def load(self) -> Dict[bytes, Dict[str, Any]]:
        """
        Devuelve raw_uid bytes → {'ip', 'last_seen': datetime, 'status'}
        """
        if not os.path.exists(self.path):
            return {}
        with open(self.path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        result = {}
        for key, info in data.items():
            result[key.encode('utf-8')] = {
                'ip': info['ip'],
                'last_seen': datetime.fromisoformat(info['last_seen']),
                'status': info.get('status', 'connected')
            }
        return result
