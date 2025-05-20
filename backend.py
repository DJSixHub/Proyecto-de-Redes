from util import get_local_ip
from discovery import Discovery
from messaging import Messaging
from pathlib import Path
import json

CONFIG_DIR = Path("config")
CONFIG_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = CONFIG_DIR / "settings.json"

# Guardar o cargar nickname
def load_nickname():
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text()).get("nickname")
    return None

def save_nickname(nick):
    SETTINGS_FILE.write_text(json.dumps({"nickname": nick}))

# Callback al recibir un mensaje de texto
def on_msg(from_id, message):
    print(f"\n📨 [{from_id}] dice: {message}")

# Callback al recibir un archivo
def on_file(from_id, filepath):
    print(f"\n📁 [{from_id}] envió archivo: {filepath}")

if __name__ == '__main__':
    saved_nick = load_nickname()
    if saved_nick:
        user = input(f"Tu UserID (ENTER para usar '{saved_nick}'): ").strip()
        if not user:
            user = saved_nick
    else:
        user = input("Tu UserID (máx. 20 caracteres): ").strip()

    user = user[:20]
    save_nickname(user)

    ip = get_local_ip()
    print(f"🖥️  Tu IP local es: {ip}")

    # Descubrimiento de vecinos
    disc = Discovery(user)
    print("🔍 Buscando vecinos...")
    peers = disc.search_peers()
    print("✅ Vecinos encontrados:")
    for uid, ip in peers.items():
        print(f" - {uid} en {ip}")

    # Iniciar mensajería
    msg = Messaging(user, on_message=on_msg, on_file=on_file)
    msg.update_peers(peers)

    while True:
        entrada = input("\nEnviar a (nickname o varios separados por coma): ").strip()
        if not entrada:
            continue
        texto = input("Mensaje: ").strip()
        if not texto:
            continue

        ids = [u.strip() for u in entrada.split(',') if u.strip()]
        for uid in ids:
            if uid in peers:
                print(f"⏳ Enviando mensaje a {uid}...")
                msg.send_message(uid, texto)
            else:
                print(f"⚠️  {uid} no está en la lista de vecinos")
