import json
import os
from datetime import datetime, UTC

class PeersStore:
    """
    Guarda y carga el mapa de peers conocidos,
    y provee decode_map para convertir nombres a bytes.
    """

    def __init__(self, path='peers.json'):
        self.path = path

    def load(self):
        """
        Carga peers.json y convierte last_seen (ISO string) a datetime UTC.
        Si falta o está corrupto, devuelve {}.
        """
        if not os.path.exists(self.path):
            return {}

        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}

            # Convertir last_seen de string a datetime UTC
            for info in data.values():
                ls = info.get('last_seen')
                if isinstance(ls, str):
                    try:
                        # Asumimos que los timestamps guardados son UTC
                        dt = datetime.fromisoformat(ls)
                        # Si el timestamp no tiene zona horaria, asumimos UTC
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=UTC)
                        info['last_seen'] = dt
                    except ValueError:
                        info['last_seen'] = datetime.now(UTC)
            return data

        except (json.JSONDecodeError, ValueError):
            return {}

    def save(self, peers_dict):
        """
        Serializa peers_dict a JSON con claves string (sin padding).
        Acepta tanto bytes como strings como claves.
        """
        # Prepara un dict apto para JSON
        json_ready = {}
        for uid, info in peers_dict.items():
            # Convertir uid a string limpio
            if isinstance(uid, bytes):
                name = uid.rstrip(b'\x00').decode('utf-8')
            else:
                name = uid.rstrip()  # Ya es string
                
            json_ready[name] = {
                'ip': info['ip'],
                # convertir datetime a ISO si es necesario
                'last_seen': (
                    info['last_seen'].isoformat()
                    if hasattr(info['last_seen'], 'isoformat')
                    else info['last_seen']
                )
            }

        directory = os.path.dirname(self.path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(json_ready, f, ensure_ascii=False, indent=2)

    def decode_map(self, raw_peers):
        """
        Dado el dict crudo de load() cuyas claves son nombres (str),
        devuelve { nombre_str: uid_bytes_padded_a_20 }.
        """
        name_map = {}
        for name_str in raw_peers.keys():
            uid_bytes = name_str.encode('utf-8')
            trimmed = uid_bytes[:20]              # recortar si >20
            padded  = trimmed.ljust(20, b'\x00')  # pad bytes a 20
            name_map[name_str] = padded
        return name_map
