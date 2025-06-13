import json
import os
from datetime import datetime, UTC

# Maneja persistencia de información de peers en formato JSON
# Convierte entre formatos legibles y binarios para almacenamiento y comunicación
# Gestiona timestamps y codificación de identificadores

# Almacena información de peers y sus últimas apariciones en la red
class PeersStore:
    # Inicializa con ruta al archivo JSON de peers
    def __init__(self, path='peers.json'):
        self.path = path

    # Carga peers desde JSON, convierte timestamps ISO a datetime UTC
    # Maneja casos de archivo ausente o datos corruptos
    def load(self):
        if not os.path.exists(self.path):
            return {}

        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}

            # Procesamiento de timestamps: convertimos strings ISO a datetime UTC
            # Esto es necesario para poder realizar comparaciones temporales precisas
            for info in data.values():
                ls = info.get('last_seen')
                if isinstance(ls, str):
                    try:
                        # Los timestamps se asumen en UTC para consistencia global
                        dt = datetime.fromisoformat(ls)
                        # Garantizamos que todos los timestamps tengan zona horaria UTC
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=UTC)
                        info['last_seen'] = dt
                    except ValueError:
                        info['last_seen'] = datetime.now(UTC)
            return data

        except (json.JSONDecodeError, ValueError):
            return {}

    # Guarda el diccionario de peers en formato JSON
    # Esta función es esencial porque:
    # 1. Maneja la conversión de identificadores binarios a strings
    # 2. Serializa timestamps datetime a formato ISO
    # 3. Crea directorios necesarios si no existen
    def save(self, peers_dict):
        # Preparamos un diccionario compatible con JSON, convirtiendo tipos complejos
        json_ready = {}
        for uid, info in peers_dict.items():
            # Limpiamos el identificador: eliminamos padding y convertimos a string
            if isinstance(uid, bytes):
                name = uid.rstrip(b'\x00').decode('utf-8')
            else:
                name = uid.rstrip()  # Ya es string
                
            json_ready[name] = {
                'ip': info['ip'],
                # Aseguramos que los timestamps se guarden en formato ISO
                'last_seen': (
                    info['last_seen'].isoformat()
                    if hasattr(info['last_seen'], 'isoformat')
                    else info['last_seen']
                )
            }

        # Creamos el directorio si no existe para evitar errores de escritura
        directory = os.path.dirname(self.path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(json_ready, f, ensure_ascii=False, indent=2)

    # Convierte nombres de peers a formato binario con padding
    # Esta función es crucial para la comunicación en red porque:
    # 1. Estandariza los identificadores a 20 bytes
    # 2. Maneja la codificación UTF-8 de nombres
    # 3. Aplica padding consistente para la red
    def decode_map(self, raw_peers):
        name_map = {}
        for name_str in raw_peers.keys():
            uid_bytes = name_str.encode('utf-8')
            trimmed = uid_bytes[:20]              # Limitamos a 20 bytes máximo
            padded  = trimmed.ljust(20, b'\x00')  # Completamos con null bytes hasta 20
            name_map[name_str] = padded
        return name_map
