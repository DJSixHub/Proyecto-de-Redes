import streamlit as st
import json
import os
from pathlib import Path
from util import get_local_ip_and_broadcast
from discovery import Discovery
from messaging import Messaging

# === Rutas y carpetas ===
CONFIG_DIR = Path("config")
CONFIG_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = CONFIG_DIR / "settings.json"
HISTORY_FILE = CONFIG_DIR / "chat_history.json"
DOWNLOADS_DIR = Path("Descargas")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# === Utilidades JSON ===
def load_json(p: Path, default: dict):
    try:
        if not p.exists() or p.stat().st_size == 0:
            p.write_text(json.dumps(default))
            return default
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        print(f"⚠️ Archivo corrupto: {p.name}, reescribiendo con valor por defecto.")
        p.write_text(json.dumps(default))
        return default

def save_json(p, data):
    p.write_text(json.dumps(data))

# === Callbacks de mensajes ===
def on_msg(sender_nick, msg):
    st.session_state.history.setdefault(sender_nick, []).append(('peer', msg))
    save_json(HISTORY_FILE, st.session_state.history)

def on_file(sender_nick, filepath):
    name = os.path.basename(filepath)
    st.session_state.history.setdefault(sender_nick, []).append(('file', name))
    save_json(HISTORY_FILE, st.session_state.history)

# === Estado inicial ===
settings = load_json(SETTINGS_FILE, {'nickname': None})
history = load_json(HISTORY_FILE, {})

if 'nickname' not in st.session_state:
    st.session_state.nickname = settings['nickname']
    st.session_state.editing_nick = False
    st.session_state.new_nick = settings['nickname'] or ''

# === Panel lateral ===
st.sidebar.title("🔧 Configuración")
st.sidebar.markdown(f"**Tu nickname:** `{st.session_state.nickname or '—'}`")

if not st.session_state.editing_nick and st.sidebar.button("Cambiar Nickname"):
    st.session_state.editing_nick = True

if st.session_state.editing_nick:
    st.session_state.new_nick = st.sidebar.text_input("Nuevo nickname", st.session_state.new_nick)
    if st.sidebar.button("OK", key='ok_nick'):
        st.session_state.nickname = st.session_state.new_nick
        settings['nickname'] = st.session_state.new_nick
        save_json(SETTINGS_FILE, settings)
        st.session_state.editing_nick = False
        st.rerun()

if not st.session_state.nickname:
    st.sidebar.warning("⚠️ Define tu nickname para continuar.")
    st.stop()

# === Inicialización única ===
if 'initialized' not in st.session_state:
    user = st.session_state.nickname
    ip, _ = get_local_ip_and_broadcast()
    disc = Discovery(user)
    msg = Messaging(user, on_message=on_msg, on_file=on_file, udp_sock=disc.sock)

    st.session_state.discovery = disc
    st.session_state.messaging = msg
    st.session_state.peers = disc.peers
    st.session_state.history = history
    st.session_state.selected_peer = None
    st.session_state.initialized = True

st.sidebar.markdown("---")

# === Búsqueda manual de vecinos ===
if st.sidebar.button("🔍 Buscar Peers"):
    peers = st.session_state.discovery.search_peers()
    st.session_state.peers = peers
    st.session_state.messaging.update_peers(peers)
    st.sidebar.success(f"{len(peers)} peer(s) encontrados.")
    for nick, ip in peers.items():
        st.sidebar.markdown(f"- `{nick}` en `{ip}`")

# === Lista de peers disponibles ===
peer_list = [nick for nick in st.session_state.peers if nick != st.session_state.nickname]

if peer_list:
    st.sidebar.subheader("🧑 Chat con:")
    selected_nick = st.sidebar.selectbox("Selecciona un peer", peer_list)
    st.session_state.selected_peer = selected_nick
else:
    st.sidebar.info("No se detectaron otros vecinos.")

# === Pantalla Principal ===
st.title("📡 Chat en LAN")

peer = st.session_state.selected_peer
if peer:
    st.subheader(f"💬 Conversación con `{peer}`")

    chat = st.session_state.history.get(peer, [])[-10:]
    for tipo, contenido in chat:
        if tipo == 'peer':
            with st.chat_message(peer, avatar="👤"):
                st.markdown(contenido)
        elif tipo == 'yo':
            with st.chat_message("Tú"):
                st.markdown(contenido)
        elif tipo == 'file':
            with st.chat_message(peer, avatar="📁"):
                st.markdown(f"📎 Archivo recibido: `{contenido}`")

    msg = st.chat_input(f"Mensaje para {peer}")
    if msg:
        result = st.session_state.messaging.send_message(peer, msg)
        if result is True:
            st.session_state.history.setdefault(peer, []).append(('yo', msg))
            save_json(HISTORY_FILE, st.session_state.history)
            st.rerun()
        elif result is False:
            st.warning(f"❌ {peer} rechazó el mensaje.")
        else:
            st.warning(f"⚠️ No hubo respuesta de {peer}.")

    uploaded = st.file_uploader("📁 Enviar archivo", key='file')
    if uploaded and st.button("📤 Subir"):
        path = DOWNLOADS_DIR / uploaded.name
        with open(path, "wb") as f:
            f.write(uploaded.read())
        st.session_state.messaging.send_file(peer, str(path))
        st.session_state.history.setdefault(peer, []).append(('yo', f"[archivo: {uploaded.name}]"))
        save_json(HISTORY_FILE, st.session_state.history)
        st.success(f"Archivo enviado a {peer}")
        st.rerun()

# === Difusión grupal ===
st.divider()
st.subheader("📢 Enviar a todos los vecinos")

msg_group = st.text_input("Mensaje grupal", key="group_input")
if st.button("Enviar a todos"):
    any_sent = False
    for nick in peer_list:
        result = st.session_state.messaging.send_message(nick, msg_group)
        if result is True:
            st.session_state.history.setdefault(nick, []).append(('yo', f"[broadcast] {msg_group}"))
            any_sent = True
    save_json(HISTORY_FILE, st.session_state.history)
    if any_sent:
        st.success("Mensaje enviado a todos los que respondieron OK.")
    else:
        st.warning("⚠️ Ningún peer respondió correctamente.")
