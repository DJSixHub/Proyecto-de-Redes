import json
import os
from datetime import datetime, UTC

# Este archivo implementa el sistema de persistencia para la información de peers conocidos.
# El flujo de datos comienza con la carga de información desde un archivo JSON, donde se
# almacenan los peers con sus IPs y timestamps de última conexión. El sistema maneja la
# conversión entre diferentes formatos (bytes/strings) para los identificadores de peers,
# asegura que los timestamps estén en UTC, y proporciona métodos para guardar y cargar
# el estado de los peers de manera consistente.

class PeersStore:
    # Clase principal que maneja la persistencia de información de peers conocidos.
    # Proporciona métodos para guardar y cargar el mapa de peers, y facilita la
    # conversión entre diferentes formatos de identificadores.
    def __init__(self, path='peers.json'):
        # Ruta al archivo de almacenamiento
        self.path = path

    # Carga la información de peers desde el archivo JSON, convirtiendo los timestamps
    # a formato datetime UTC. Es necesario para recuperar el estado previo del sistema
    # y mantener la consistencia temporal.
    def load(self):
        # Si el archivo no existe, retornamos un mapa vacío
        if not os.path.exists(self.path):
            return {}

        try:
            # Cargamos y validamos el contenido JSON
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}

            # Procesamos los timestamps para asegurar formato UTC
            for info in data.values():
                ls = info.get('last_seen')
                if isinstance(ls, str):
                    try:
                        dt = datetime.fromisoformat(ls)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=UTC)
                        info['last_seen'] = dt
                    except ValueError:
                        info['last_seen'] = datetime.now(UTC)
            return data

        except (json.JSONDecodeError, ValueError):
            return {}

    # Guarda el mapa de peers en formato JSON, manejando la conversión de
    # identificadores y asegurando que los timestamps estén en formato ISO.
    # Es necesario para mantener la persistencia del estado del sistema.
    def save(self, peers_dict):
        # Preparamos el diccionario para serialización JSON
        json_ready = {}
        for uid, info in peers_dict.items():
            # Convertimos identificadores de bytes a string si es necesario
            if isinstance(uid, bytes):
                name = uid.rstrip(b'\x00').decode('utf-8')
            else:
                name = uid.rstrip()
                
            # Aseguramos que los timestamps estén en formato ISO
            json_ready[name] = {
                'ip': info['ip'],
                'last_seen': (
                    info['last_seen'].isoformat()
                    if hasattr(info['last_seen'], 'isoformat')
                    else info['last_seen']
                )
            }

        # Creamos el directorio si no existe
        directory = os.path.dirname(self.path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        # Guardamos el archivo JSON con formato legible
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(json_ready, f, ensure_ascii=False, indent=2)

    # Convierte los identificadores de peers del formato string al formato bytes
    # requerido por el protocolo. Es necesario para mantener la compatibilidad
    # entre el almacenamiento en JSON y el protocolo de comunicación.
    def decode_map(self, raw_peers):
        # Mapa para la conversión de nombres
        name_map = {}
        for name_str in raw_peers.keys():
            # Convertimos a bytes y normalizamos a 20 bytes
            uid_bytes = name_str.encode('utf-8')
            trimmed = uid_bytes[:20]
            padded  = trimmed.ljust(20, b'\x00')
            name_map[name_str] = padded
        return name_map
