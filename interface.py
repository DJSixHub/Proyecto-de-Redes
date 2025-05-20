import streamlit as st
import json
import os
from pathlib import Path
from util import get_local_ip_and_broadcast
from discovery import Discovery
from messaging import Messaging

SETTINGS_FILE = Path('settings.json')
HISTORY_FILE = Path('chat_history.json')
DOWNLOADS_DIR = Path('Descargas')
DOWNLOADS_DIR.mkdir(exist_ok=True)

def load_json(p, default):
    if p.exists():
        return json.loads(p.read_text())
    p.write_text(json.dumps(default))
    return default

def save_json(p, data):
    p.write_text(json.dumps(data))

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

# === Inicializar componentes ===
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

# === Buscar vecinos manualmente ===
if st.sidebar.button("🔍 Buscar Peers"):
    peers = st.session_state.discovery.search_peers()
    st.session_state.peers = peers
    st.session_state.messaging.update_peers(peers)
    st.sidebar.success(f"{len(peers)} peer(s) encontrados.")
    for nick, ip in peers.items():
        st.sidebar.markdown(f"- `{nick}` en `{ip}`")

# === Listar peers (excluye a sí mismo)
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
        st.session_state.messaging.send_message(peer, msg)
        st.session_state.history.setdefault(peer, []).append(('yo', msg))
        save_json(HISTORY_FILE, st.session_state.history)
        st.rerun()

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
    for nick in peer_list:
        st.session_state.messaging.send_message(nick, msg_group)
        st.session_state.history.setdefault(nick, []).append(('yo', f"[broadcast] {msg_group}"))
    save_json(HISTORY_FILE, st.session_state.history)
    st.success("Mensaje enviado a todos.")
