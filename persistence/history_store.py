# persistence/history_store.py

import os
import json
from datetime import datetime, UTC
from typing import List, Dict, Any

class HistoryStore:
    """
    Maneja historial persistente de mensajes y archivos.
    Cada entrada: {'type', 'sender', 'recipient', 'message|filename', 'timestamp'}
    Los timestamps se almacenan en formato ISO con zona horaria UTC.
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

        # Asegurar que el timestamp tenga zona horaria UTC
        if isinstance(entry['timestamp'], datetime):
            if entry['timestamp'].tzinfo is None:
                entry['timestamp'] = entry['timestamp'].replace(tzinfo=UTC)
            entry['timestamp'] = entry['timestamp'].isoformat()

        history.append(entry)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    def append_message(self, sender: str, recipient: str, message: str, timestamp: datetime):
        # Asegurar que el timestamp tenga zona horaria UTC
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
            
        entry = {
            'type': 'message',
            'sender': sender,
            'recipient': recipient,
            'message': message,
            'timestamp': timestamp.isoformat()
        }
        self._append(entry)

    def append_file(self, sender: str, recipient: str, filename: str, timestamp: datetime):
        # Asegurar que el timestamp tenga zona horaria UTC
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
            
        entry = {
            'type': 'file',
            'sender': sender,
            'recipient': recipient,
            'filename': filename,
            'timestamp': timestamp.isoformat()
        }
        self._append(entry)

    def get_conversation(self, peer: str) -> List[Dict[str, Any]]:
        """
        Devuelve la conversación entre el usuario actual y el peer indicado,
        incluyendo mensajes globales si peer no es '*global*'.
        Los timestamps se devuelven como datetime UTC.
        """
        try:
            history = self.load_raw()
        except Exception as e:
            print(f"Error cargando historial: {e}")
            return []

        # Convertir timestamps a datetime UTC
        for item in history:
            if isinstance(item.get('timestamp'), str):
                try:
                    dt = datetime.fromisoformat(item['timestamp'])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    item['timestamp'] = dt
                except ValueError as e:
                    print(f"Error parseando timestamp: {e}")
                    item['timestamp'] = datetime.now(UTC)

        # Si pedimos globales, solo devolver globales
        if peer == "*global*":
            return [
                item for item in history
                if item.get('recipient') == "*global*"
            ]

        # Si pedimos conversación con peer, incluir mensajes privados y globales
        return [
            item for item in history
            if (
                # Mensajes privados con el peer
                item.get('sender') == peer or 
                item.get('recipient') == peer or
                # Mensajes globales (excepto los míos)
                (item.get('recipient') == "*global*" and item.get('sender') != peer)
            )
        ]

    def load_raw(self) -> List[Dict[str, Any]]:
        """
        Carga el historial bruto desde el archivo JSON.
        Los timestamps se devuelven como strings ISO con zona horaria UTC.
        """
        if not os.path.exists(self.path):
            return []
        with open(self.path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
