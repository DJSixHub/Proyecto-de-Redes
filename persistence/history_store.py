# Gestiona historial de mensajes y archivos intercambiados entre usuarios
# Almacena cronológicamente cada interacción en JSON con metadatos
# Utiliza timestamps UTC para consistencia temporal

import os
import json
from datetime import datetime, UTC
from typing import List, Dict, Any

# Gestiona almacenamiento de historial de comunicaciones
# Registra interacciones y permite acceso a conversaciones privadas/globales
class HistoryStore:
    # Inicializa almacén con ruta al archivo JSON
    def __init__(self, filename: str = "history.json"):
        folder = os.path.dirname(os.path.abspath(__file__))
        self.path = os.path.join(folder, filename)
        os.makedirs(folder, exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump([], f)

    # Agrega entrada al historial con normalización de timestamp
    def _append(self, entry: Dict[str, Any]):
        try:
            history = self.load_raw()
        except Exception:
            history = []

        # Normalización del timestamp a formato ISO con zona horaria UTC
        # Esto es crucial para mantener consistencia temporal en la aplicación
        if isinstance(entry['timestamp'], datetime):
            if entry['timestamp'].tzinfo is None:
                entry['timestamp'] = entry['timestamp'].replace(tzinfo=UTC)
            entry['timestamp'] = entry['timestamp'].isoformat()

        history.append(entry)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    # Agrega un mensaje de texto al historial
    # Los parámetros incluyen remitente, destinatario, contenido y timestamp
    def append_message(self, sender: str, recipient: str, message: str, timestamp: datetime):
        # Aseguramos consistencia temporal con UTC
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

    # Agrega un registro de transferencia de archivo al historial
    # Similar a append_message pero para archivos
    def append_file(self, sender: str, recipient: str, filename: str, timestamp: datetime):
        # Aseguramos consistencia temporal con UTC
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

    # Recupera la conversación completa con un peer específico
    # Esta función es crucial porque:
    # 1. Maneja tanto mensajes privados como globales
    # 2. Convierte timestamps a objetos datetime
    # 3. Filtra mensajes relevantes según el contexto
    def get_conversation(self, peer: str) -> List[Dict[str, Any]]:
        try:
            history = self.load_raw()
        except Exception as e:
            print(f"Error cargando historial: {e}")
            return []

        # Procesamiento de timestamps: convertimos strings ISO a datetime UTC
        # Esto es necesario para poder realizar operaciones temporales con los mensajes
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

        # Manejo especial para mensajes globales
        if peer == "*global*":
            return [
                item for item in history
                if item.get('recipient') == "*global*"
            ]

        # Filtrado de mensajes para conversaciones privadas
        # Incluye mensajes directos entre el usuario y el peer
        # Importante: Filtramos por el nombre del peer, no por su IP
        # para mantener el historial incluso si cambia la IP
        filtered_messages = [
            item for item in history
            if (
                # Mensajes enviados por el peer al usuario actual
                (item.get('sender') == peer) or 
                # Mensajes enviados al peer
                (item.get('recipient') == peer)
            )
        ]
        
        # Ordenamos los mensajes por timestamp para mostrarlos cronológicamente
        filtered_messages.sort(key=lambda x: x['timestamp'])
        
        return filtered_messages

    # Carga el historial completo sin procesar
    # Esta función es importante porque:
    # 1. Proporciona acceso directo a los datos raw
    # 2. Mantiene los timestamps en formato ISO
    # 3. Maneja casos de archivo vacío o inexistente
    def load_raw(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
