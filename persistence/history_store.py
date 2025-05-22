# persistence/history_store.py

import os
import json
from datetime import datetime
from typing import List, Dict, Any

class HistoryStore:
    """
    Maneja historial persistente de mensajes y archivos.
    Cada entrada: {'type', 'sender', 'recipient', 'message|filename', 'timestamp'}
    """

    def __init__(self, filename: str = "history.json"):
        folder = os.path.dirname(os.path.abspath(__file__))
        self.path = os.path.join(folder, filename)
        os.makedirs(folder, exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def _append(self, entry: Dict[str, Any]):
        try:
            history = self.load_raw()
        except Exception:
            history = []

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

    def get_conversation(self, peer: str) -> List[Dict[str, Any]]:
        """Devuelve la conversación entre el usuario actual y el peer indicado."""
        try:
            history = self.load_raw()
        except Exception:
            return []

        return [
            item for item in history
            if item.get('sender') == peer or item.get('recipient') == peer
        ]

    def load_raw(self) -> List[Dict[str, Any]]:
        """Carga el historial bruto desde el archivo JSON."""
        if not os.path.exists(self.path):
            return []
        with open(self.path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
