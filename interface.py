import streamlit as st
import json
import time
from pathlib import Path

# === Configuración ===
SHARED_DIR = Path("shared")
SHARED_DIR.mkdir(parents=True, exist_ok=True)

# Archivos
HISTORY_FILE = SHARED_DIR / "history.json"
PEERS_FILE = SHARED_DIR / "peers.json"
OUTBOX_FILE = SHARED_DIR / "outbox.json"
SETTINGS_FILE = SHARED_DIR / "settings.json"
SCAN_FILE = SHARED_DIR / "scan_now.json"
NICKMAP_FILE = SHARED_DIR / "nick_map.json"

# === Utilidades JSON ===
def load_json(p: Path, default: dict):
    try:
        if not p.exists() or p.stat().st_size == 0:
            return default
        return json.loads(p.read_text())
    except:
        return default

def save_json(p: Path, data: dict):
    p.write_text(json.dumps(data))

def append_outbox(to: str, message: str):
    outbox = load_json(OUTBOX_FILE, [])
    outbox.append({"to": to, "message": message})
    save_json(OUTBOX_FILE, outbox)

# === Estado inicial ===
settings = load_json(SETTINGS_FILE, {"nickname": "usuario"})
if "nickname" not in st.session_state:
    st.session_state.nickname = settings["nickname"]
if "selected_peer" not in st.session_state:
    st.session_state.selected_peer = None
if "editing_nick" not in st.session_state:
    st.session_state.editing_nick = False
if "new_nick" not in st.session_state:
    st.session_state.new_nick = ""

# === Cargar datos ===
history = load_json(HISTORY_FILE, {})
peers_raw = load_json(PEERS_FILE, {})
nick_map = load_json(NICKMAP_FILE, {})

# === DEBUG sin filtro por last_seen ===
peers = {uid: data["ip"] for uid, data in peers_raw.items()}

# === BARRA LATERAL ===
st.sidebar.title(f"👤 {st.session_state.nickname}")

# Cambiar nickname
if not st.session_state.editing_nick:
    if st.sidebar.button("✏️ Cambiar nombre de usuario"):
        st.session_state.editing_nick = True
else:
    st.sidebar.text_input("Nuevo nombre:", key="new_nick")
    if st.sidebar.button("✅ OK"):
        st.session_state.nickname = st.session_state.new_nick.strip()[:20] or "usuario"
        save_json(SETTINGS_FILE, {"nickname": st.session_state.nickname})
        st.session_state.editing_nick = False
        st.rerun()

# Buscar peers manualmente
if st.sidebar.button("🔍 Buscar Peers"):
    save_json(SCAN_FILE, {"scan": True})
    st.sidebar.success("Solicitud enviada para buscar vecinos.")

# Mostrar peers conectados
st.sidebar.markdown("### 🧑‍🤝‍🧑 Peers activos")
if peers:
    for uid, ip in peers.items():
        nick = nick_map.get(uid, uid)
        st.sidebar.markdown(f"- `{nick}` @ `{ip}`")

    peer_selected = st.sidebar.selectbox("Chatear con:", list(peers.keys()), format_func=lambda uid: nick_map.get(uid, uid))
    st.session_state.selected_peer = peer_selected
else:
    st.sidebar.warning("No hay peers conectados.")

# === DEBUG PANEL ===
st.sidebar.markdown("---")
st.sidebar.markdown("### 🐞 DEBUG: peers_raw")
st.sidebar.json(peers_raw)

# === UI Principal ===
st.title("📡 Chat Local LCP")

peer = st.session_state.selected_peer
if peer:
    nick = nick_map.get(peer, peer)
    st.subheader(f"🗨️ Conversación con `{nick}`")
    chat = history.get(peer, [])
    for kind, msg in chat[-10:]:
        if kind == "peer":
            with st.chat_message(nick, avatar="👤"):
                st.markdown(msg)
        elif kind == "yo":
            with st.chat_message("Tú"):
                st.markdown(msg)
        elif kind == "file":
            with st.chat_message(nick, avatar="📁"):
                st.markdown(f"📎 Archivo recibido: `{msg}`")

    user_msg = st.chat_input(f"Mensaje para {nick}")
    if user_msg:
        append_outbox(peer, user_msg)
        history.setdefault(peer, []).append(("yo", user_msg))
        save_json(HISTORY_FILE, history)
        st.rerun()

# === Difusión grupal simulada ===
if peers:
    st.divider()
    st.subheader("📢 Enviar mensaje a todos")
    group_msg = st.text_input("Mensaje grupal")
    if st.button("Enviar a todos"):
        for uid in peers:
            append_outbox(uid, group_msg)
            history.setdefault(uid, []).append(("yo", f"[broadcast] {group_msg}"))
        save_json(HISTORY_FILE, history)
        st.success("Mensaje enviado.")
