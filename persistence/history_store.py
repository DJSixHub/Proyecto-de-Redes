# persistence/history_store.py

import os
import json
from datetime import datetime
from typing import List, Dict

class HistoryStore:
    """
    Guarda y carga el historial de mensajes y archivos en JSON dentro de esta carpeta.
    """

    def __init__(self, filename: str = "history.json"):
        folder = os.path.dirname(os.path.abspath(__file__))
        self.path = os.path.join(folder, os.path.basename(filename))
        os.makedirs(folder, exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def append_message(self, sender: str, message: str, timestamp: datetime):
        entry = {
            'type': 'message',
            'sender': sender,
            'message': message,
            'timestamp': timestamp.isoformat()
        }
        self._append(entry)

    def append_file(self, sender: str, filename: str, timestamp: datetime):
        entry = {
            'type': 'file',
            'sender': sender,
            'filename': filename,
            'timestamp': timestamp.isoformat()
        }
        self._append(entry)

    def load(self) -> List[Dict]:
        with open(self.path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for e in data:
            e['timestamp'] = datetime.fromisoformat(e['timestamp'])
        return data

    def _append(self, entry: Dict):
        history = self.load()
        history.append(entry)
        serial = []
        for e in history:
            item = e.copy()
            if isinstance(item.get('timestamp'), datetime):
                item['timestamp'] = item['timestamp'].isoformat()
            serial.append(item)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(serial, f, ensure_ascii=False, indent=2)
