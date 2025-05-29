# persistence/history_store.py

import os
import json
from datetime import datetime, UTC
from typing import List, Dict, Any

# Este archivo implementa el sistema de persistencia para el historial de mensajes y archivos
# del chat. El flujo de datos comienza con la inicialización del almacenamiento en un archivo JSON,
# donde cada entrada contiene información sobre el tipo de contenido (mensaje o archivo), remitente,
# destinatario y marca de tiempo. Los datos se almacenan con timestamps en UTC y se manejan
# conversaciones tanto privadas como globales. El sistema garantiza la persistencia entre sesiones
# y proporciona métodos para agregar y recuperar el historial de comunicaciones.

class HistoryStore:
    # Clase principal que gestiona el almacenamiento persistente del historial de chat.
    # Maneja la escritura y lectura de mensajes y archivos en formato JSON, asegurando
    # que todos los timestamps estén en UTC y que los datos sean consistentes.
    def __init__(self, filename: str = "history.json"):
        # Configuración del archivo de almacenamiento
        folder = os.path.dirname(os.path.abspath(__file__))
        self.path = os.path.join(folder, filename)
        
        # Creamos el directorio y el archivo si no existen
        os.makedirs(folder, exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump([], f)

    # Método interno que maneja la lógica común de agregar entradas al historial,
    # asegurando que los timestamps estén en formato UTC y manejando la persistencia
    # en el archivo JSON.
    def _append(self, entry: Dict[str, Any]):
        # Cargamos el historial existente o iniciamos uno nuevo
        try:
            history = self.load_raw()
        except Exception:
            history = []

        # Normalizamos el timestamp a formato ISO con zona UTC
        if isinstance(entry['timestamp'], datetime):
            if entry['timestamp'].tzinfo is None:
                entry['timestamp'] = entry['timestamp'].replace(tzinfo=UTC)
            entry['timestamp'] = entry['timestamp'].isoformat()

        # Agregamos la entrada y guardamos el historial actualizado
        history.append(entry)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    # Agrega un mensaje de texto al historial, asegurando que el timestamp esté en UTC.
    # Este método es necesario para mantener un registro de todas las comunicaciones
    # de texto entre usuarios.
    def append_message(self, sender: str, recipient: str, message: str, timestamp: datetime):
        # Aseguramos que el timestamp tenga zona horaria UTC
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
            
        # Creamos la entrada con todos los metadatos necesarios
        entry = {
            'type': 'message',
            'sender': sender,
            'recipient': recipient,
            'message': message,
            'timestamp': timestamp.isoformat()
        }
        self._append(entry)

    # Agrega un registro de transferencia de archivo al historial, asegurando que el
    # timestamp esté en UTC. Este método es necesario para mantener un registro de
    # todos los archivos compartidos entre usuarios.
    def append_file(self, sender: str, recipient: str, filename: str, timestamp: datetime):
        # Aseguramos que el timestamp tenga zona horaria UTC
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
            
        # Creamos la entrada con todos los metadatos necesarios
        entry = {
            'type': 'file',
            'sender': sender,
            'recipient': recipient,
            'filename': filename,
            'timestamp': timestamp.isoformat()
        }
        self._append(entry)

    # Recupera la conversación completa con un peer específico, incluyendo mensajes
    # globales si no se está solicitando específicamente el historial global.
    # Este método es esencial para mostrar el historial de chat en la interfaz.
    def get_conversation(self, peer: str) -> List[Dict[str, Any]]:
        # Intentamos cargar el historial completo
        try:
            history = self.load_raw()
        except Exception as e:
            print(f"Error cargando historial: {e}")
            return []

        # Procesamos los timestamps a objetos datetime con UTC
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

        # Para mensajes globales, solo retornamos mensajes con recipient "*global*"
        if peer == "*global*":
            return [
                item for item in history
                if item.get('recipient') == "*global*"
            ]

        # Para conversaciones privadas, incluimos:
        # 1. Mensajes enviados por el peer
        # 2. Mensajes enviados al peer
        # 3. Mensajes globales que NO son del peer (para evitar duplicados)
        return [
            item for item in history
            if (
                item.get('sender') == peer or 
                item.get('recipient') == peer or
                (item.get('recipient') == "*global*" and item.get('sender') != peer)
            )
        ]

    # Carga el historial completo desde el archivo JSON sin procesar los timestamps.
    # Este método es necesario para operaciones internas que requieren acceso
    # a los datos brutos del historial.
    def load_raw(self) -> List[Dict[str, Any]]:
        # Si el archivo no existe, retornamos una lista vacía
        if not os.path.exists(self.path):
            return []
            
        # Leemos y validamos el contenido del archivo
        with open(self.path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
