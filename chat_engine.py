import json
import time
import threading
from pathlib import Path
from util import get_local_ip_and_broadcast
from discovery import Discovery
from messaging import Messaging
from protocol import pack_header, unpack_response, RESPONSE_SIZE

# === Configuración general ===
SHARED_DIR = Path("shared")
SHARED_DIR.mkdir(parents=True, exist_ok=True)

# Archivos compartidos
HISTORY_FILE = SHARED_DIR / "history.json"
PEERS_FILE = SHARED_DIR / "peers.json"
OUTBOX_FILE = SHARED_DIR / "outbox.json"
SCAN_FILE = SHARED_DIR / "scan_now.json"
SETTINGS_FILE = SHARED_DIR / "settings.json"
NICKMAP_FILE = SHARED_DIR / "nick_map.json"

# === Leer nickname
def load_json(p: Path, default):
    try:
        if not p.exists() or p.stat().st_size == 0:
            p.write_text(json.dumps(default))
            return default
        return json.loads(p.read_text())
    except:
        return default

def save_json(p: Path, data):
    p.write_text(json.dumps(data))

settings = load_json(SETTINGS_FILE, {"nickname": "usuario"})
USER_ID = settings.get("nickname", "usuario")

# === Callbacks de red ===
def on_message(sender, message):
    history = load_json(HISTORY_FILE, {})

    if message.strip() == "#HISTORY_REQUEST":
        last_msgs = history.get(sender, [])[-10:]
        response = json.dumps(last_msgs)
        msg.send_message(sender, f"#HISTORY_RESPONSE:{response}")
        return

    if message.startswith("#HISTORY_RESPONSE:"):
        payload = message[len("#HISTORY_RESPONSE:"):].strip()
        try:
            msgs = json.loads(payload)
            for kind, content in msgs:
                history.setdefault(sender, []).append((kind, content))
            save_json(HISTORY_FILE, history)
            print(f"[MSG] Historial restaurado desde {sender}")
        except Exception as e:
            print(f"[MSG] Error al parsear historial: {e}")
        return

    history.setdefault(sender, []).append(("peer", message))
    save_json(HISTORY_FILE, history)
    print(f"[MSG] {sender}: {message}")

def on_file(sender, filepath):
    history = load_json(HISTORY_FILE, {})
    history.setdefault(sender, []).append(("file", filepath))
    save_json(HISTORY_FILE, history)
    print(f"[FILE] {sender} envió {filepath}")

# === Motor principal ===
def run_chat_engine():
    print(f"[ENGINE] Iniciando como '{USER_ID}'...")

    disc = Discovery(USER_ID)
    global msg
    msg = Messaging(USER_ID, on_message=on_message, on_file=on_file, udp_sock=disc.sock)

    def discovery_loop():
        print("[DEBUG] discovery_loop corriendo...")
        while True:
            do_scan = False
            if SCAN_FILE.exists():
                print("[DEBUG] SCAN_FILE detectado")
                try:
                    trigger = json.loads(SCAN_FILE.read_text())
                    print(f"[DEBUG] Contenido de SCAN_FILE: {trigger}")
                    if trigger.get("scan") is True:
                        do_scan = True
                        SCAN_FILE.unlink()
                except Exception as e:
                    print(f"[ERROR] leyendo SCAN_FILE: {e}")

            if do_scan:
                peers = disc.search_peers()
                print(f"[DEBUG] Vecinos detectados por discovery: {peers}")

                timestamp = time.time()
                extended_peers = {}
                nick_map = load_json(NICKMAP_FILE, {})
                for uid, ip in peers.items():
                    extended_peers[uid] = {"ip": ip, "last_seen": timestamp}
                    if uid not in nick_map:
                        nick_map[uid] = uid

                save_json(PEERS_FILE, extended_peers)
                save_json(NICKMAP_FILE, nick_map)
                msg.update_peers({uid: data["ip"] for uid, data in extended_peers.items()})
                print(f"[DEBUG] peers actualizados desde discovery: {extended_peers}")

                previous_peers = load_json(PEERS_FILE, {})
                new_peers = [uid for uid in peers if uid not in previous_peers]
                for new_uid in new_peers:
                    print(f"[ENGINE] Solicitando historial a {new_uid}")
                    msg.send_message(new_uid, "#HISTORY_REQUEST")

            time.sleep(10)

    def outbox_loop():
        while True:
            outbox = load_json(OUTBOX_FILE, [])
            new_outbox = []
            for entry in outbox:
                peer = entry.get("to")
                message = entry.get("message")
                if peer and message:
                    result = msg.send_message(peer, message)
                    print(f"[OUTBOX] → {peer}: {'OK' if result else 'FAIL'}")
                    if not result:
                        new_outbox.append(entry)
            save_json(OUTBOX_FILE, new_outbox)
            time.sleep(1)

    def heartbeat_loop():
        while True:
            peers = load_json(PEERS_FILE, {})
            current_time = time.time()
            changed = False

            for uid, info in list(peers.items()):
                ip = info.get("ip")
                pkt = pack_header(USER_ID, uid, 0)

                responded = False
                for attempt in range(2):
                    try:
                        disc.sock.sendto(pkt, (ip, 9990))
                        disc.sock.settimeout(1.5)
                        response, _ = disc.sock.recvfrom(RESPONSE_SIZE)
                        status, responder = unpack_response(response)
                        if status == 0 and responder == uid:
                            peers[uid]["last_seen"] = current_time
                            responded = True
                            break
                    except:
                        continue

                if not responded:
                    print(f"[HEARTBEAT] {uid} no respondió tras 2 intentos. Eliminando.")
                    del peers[uid]
                    changed = True

            if changed:
                save_json(PEERS_FILE, peers)
                msg.update_peers({uid: data["ip"] for uid, data in peers.items()})

            time.sleep(10)

    threading.Thread(target=discovery_loop, daemon=True).start()
    threading.Thread(target=outbox_loop, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    while True:
        time.sleep(1)

if __name__ == "__main__":
    run_chat_engine()
