# persistence/history_store.py

import os
import json
from datetime import datetime
from typing import List, Dict

class HistoryStore:
    """
    Historial de mensajes y archivos.
    Cada entrada incluye sender, recipient, message/filename, timestamp.
    """

    def __init__(self, filename: str = "history.json"):
        folder = os.path.dirname(os.path.abspath(__file__))
        self.path = os.path.join(folder, filename)
        os.makedirs(folder, exist_ok=True)
        # Si no existe, crear como lista vacía
        if not os.path.exists(self.path):
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def load_raw(self) -> List[Dict]:
        """
        Lee el archivo JSON sin parsear timestamps.
        Si el archivo está vacío o es JSON inválido, devuelve [].
        """
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return []
                return json.loads(content)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def load(self) -> List[Dict]:
        """
        Lee y parsea timestamps a datetime.
        """
        data = self.load_raw()
        for e in data:
            try:
                e['timestamp'] = datetime.fromisoformat(e['timestamp'])
            except Exception:
                e['timestamp'] = None
        return data

    def _append(self, entry: Dict):
        history = self.load_raw()
        history.append(entry)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    def append_message(self, sender: str, recipient: str, message: str, timestamp: datetime):
        entry = {
            'type': 'message',
            'sender': sender,
            'recipient': recipient,
            'message': message,
            'timestamp': timestamp.isoformat()
        }
        self._append(entry)

    def append_file(self, sender: str, recipient: str, filename: str, timestamp: datetime):
        entry = {
            'type': 'file',
            'sender': sender,
            'recipient': recipient,
            'filename': filename,
            'timestamp': timestamp.isoformat()
        }
        self._append(entry)

    def get_conversation(self, peer: str) -> List[Dict]:
        """
        Devuelve la conversación completa (mensajes y archivos)
        con `peer`, ordenada cronológicamente.
        """
        conv = [
            e for e in self.load()
            if e.get('type') in ('message', 'file')
               and (e.get('sender') == peer or e.get('recipient') == peer)
        ]
        return sorted(conv, key=lambda e: e.get('timestamp') or datetime.min)
