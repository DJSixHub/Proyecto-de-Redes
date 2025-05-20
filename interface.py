import streamlit as st
import json
from pathlib import Path
from util import get_local_ip_and_broadcast
from discovery import Discovery
from messaging import Messaging
import os

SETTINGS_FILE = Path('settings.json')
HISTORY_FILE  = Path('chat_history.json')
DOWNLOADS_DIR = Path('Descargas')
DOWNLOADS_DIR.mkdir(exist_ok=True)

def load_json(p, default):
    if p.exists():
        return json.loads(p.read_text())
    p.write_text(json.dumps(default))
    return default

def save_json(p, data):
    p.write_text(json.dumps(data))

def on_msg(sender, msg):
    st.session_state.history.setdefault(sender, []).append(('peer', msg))
    save_json(HISTORY_FILE, st.session_state.history)

def on_file(sender, filepath):
    name = os.path.basename(filepath)
    st.session_state.history.setdefault(sender, []).append(('file', name))
    save_json(HISTORY_FILE, st.session_state.history)

# Estado inicial
settings = load_json(SETTINGS_FILE, {'nickname': None})
history  = load_json(HISTORY_FILE, {})

if 'nickname' not in st.session_state:
    st.session_state.nickname     = settings['nickname']
    st.session_state.editing_nick = False
    st.session_state.new_nick     = settings['nickname'] or ''

# Sidebar para nickname
st.sidebar.markdown(f"### Usuario: **{st.session_state.nickname or '—'}**")
if not st.session_state.editing_nick and st.sidebar.button("Cambiar Nickname"):
    st.session_state.editing_nick = True
if st.session_state.editing_nick:
    st.session_state.new_nick = st.sidebar.text_input("Nuevo nickname", st.session_state.new_nick)
    if st.sidebar.button("OK", key='ok_nick'):
        st.session_state.nickname = st.session_state.new_nick
        settings['nickname'] = st.session_state.new_nick
        save_json(SETTINGS_FILE, settings)
        st.session_state.editing_nick = False

if not st.session_state.nickname:
    st.sidebar.warning("Define tu nickname para continuar.")
    st.stop()

# Inicializar instancia
if 'initialized' not in st.session_state:
    user = st.session_state.nickname
    ip, _ = get_local_ip_and_broadcast()  # <-- ✅ corregido
    disc = Discovery(user)
    msg  = Messaging(user,
                     on_message=on_msg,
                     on_file=on_file,
                     udp_sock=disc.sock)
    st.session_state.discovery    = disc
    st.session_state.peers        = disc.peers
    st.session_state.messaging    = msg
    st.session_state.history      = history
    st.session_state.selected_uid = None
    st.session_state.initialized  = True

# Título
st.title("💬 Chat P2P en LAN")

# Buscar vecinos
if st.button("🔍 Buscar Peers"):
    st.session_state.peers = st.session_state.discovery.search_peers()
    st.success(f"Se encontraron {len(st.session_state.peers)} vecinos.")
    for uid, ip in st.session_state.peers.items():
        st.markdown(f"- **{uid}** en `{ip}`")

peer_ids = list(st.session_state.peers.keys())

# Chat general
st.subheader("📨 Enviar a todos")
group_msg = st.text_input("Mensaje para todos", key='group_input')
if st.button("📢 Difundir"):
    for peer in peer_ids:
        st.session_state.messaging.send_message(peer, group_msg)
    st.success("Mensaje enviado a todos.")

# Chat uno a uno
if peer_ids:
    st.subheader("💬 Chat individual")
    st.session_state.selected_uid = st.selectbox("Selecciona un peer", peer_ids)

    if st.session_state.selected_uid:
        uid = st.session_state.selected_uid
        chat = st.session_state.history.get(uid, [])[-10:]

        for tipo, contenido in chat:
            if tipo == 'peer':
                st.markdown(f"🟦 **{uid}**: {contenido}")
            elif tipo == 'yo':
                st.markdown(f"🟩 Tú: {contenido}")
            elif tipo == 'file':
                st.markdown(f"📎 **{uid} te envió:** `{contenido}`")

        col1, col2 = st.columns([4, 1])
        with col1:
            msg = st.text_input("Tu mensaje", key='msg_input')
        with col2:
            if st.button("Enviar"):
                st.session_state.messaging.send_message(uid, msg)
                st.session_state.history.setdefault(uid, []).append(('yo', msg))
                save_json(HISTORY_FILE, st.session_state.history)
                st.rerun()

        # Enviar archivo
        uploaded = st.file_uploader("📁 Enviar archivo", key='file')
        if uploaded and st.button("Subir"):
            path = DOWNLOADS_DIR / uploaded.name
            with open(path, "wb") as f:
                f.write(uploaded.read())
            st.session_state.messaging.send_file(uid, str(path))
            st.session_state.history.setdefault(uid, []).append(('yo', f"[archivo: {uploaded.name}]"))
            save_json(HISTORY_FILE, st.session_state.history)
            st.success(f"Archivo enviado a {uid}")
            st.rerun()
else:
    st.info("No se encontraron peers aún. Haz clic en 'Buscar Peers'.")
