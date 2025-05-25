# persistence/peers_store.py

import json
import os

class PeersStore:
    """
    Guarda y carga el mapa de peers conocido:
      { uid_bytes: {'ip': 'x.x.x.x', 'last_seen': timestamp}, ... }
    en un fichero JSON.
    """

    def __init__(self, path='peers.json'):
        # Puedes parametrizar la ruta si lo deseas
        self.path = path

    def load(self):
        """
        Intenta cargar el JSON de peers. 
        Si el fichero no existe, está vacío o es inválido,
        devuelve un dict vacío en vez de lanzar excepción.
        """
        if not os.path.exists(self.path):
            return {}

        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Asegurarse que devuelve un dict
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, ValueError):
            # Fichero vacío o JSON malformado
            return {}

    def save(self, peers_dict):
        """
        Serializa el dict de peers a JSON, creando/reescribiendo el fichero.
        """
        # Asegurarse de la carpeta existe si usas rutas con subdirectorios
        directory = os.path.dirname(self.path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(peers_dict, f, ensure_ascii=False, indent=2)
