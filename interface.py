import streamlit as st
import json
from pathlib import Path
from util import get_local_ip
from discovery import Discovery
from messaging import Messaging

# Rutas de persistencia
SETTINGS_FILE = Path('settings.json')
HISTORY_FILE  = Path('chat_history.json')
DOWNLOADS_DIR = Path('Descargas')

# Utilidades JSON
def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text())
    path.write_text(json.dumps(default))
    return default

def save_json(path, data):
    path.write_text(json.dumps(data))

# Carga settings e historial
settings = load_json(SETTINGS_FILE, {'nickname': None})
history  = load_json(HISTORY_FILE, {})

# Inicializa estado de nickname y edición
if 'nickname' not in st.session_state:
    st.session_state.nickname     = settings.get('nickname')
    st.session_state.editing_nick = False
    st.session_state.new_nick     = st.session_state.nickname or ''

# Sidebar: mostrar y cambiar nickname
st.sidebar.markdown(f"### Usuario: **{st.session_state.nickname or '—'}**")
if not st.session_state.editing_nick:
    if st.sidebar.button("Cambiar Nickname"):
        st.session_state.editing_nick = True

if st.session_state.editing_nick:
    st.session_state.new_nick = st.sidebar.text_input(
        "Nuevo nickname", value=st.session_state.new_nick, key='nick_input'
    )
    if st.sidebar.button("OK", key='ok_nick'):
        st.session_state.nickname     = st.session_state.new_nick
        settings['nickname']          = st.session_state.new_nick
        save_json(SETTINGS_FILE, settings)
        st.session_state.editing_nick = False

# Detener si no hay nickname
if not st.session_state.nickname:
    st.sidebar.warning("Define tu nickname para continuar.")
    st.stop()

# Callbacks
def on_msg(from_id, message):
    peer = st.session_state.current_peer
    entry = f"[{from_id} ➤ Tú] {message}"
    st.session_state.chat.append(entry)
    st.session_state.history.setdefault(peer, []).append(entry)
    save_json(HISTORY_FILE, st.session_state.history)

def on_file(from_id, data):
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    fname = DOWNLOADS_DIR / f"{from_id}_{len(data)}.bin"
    fname.write_bytes(data)
    entry = f"[Archivo de {from_id} guardado: {fname.name}]"
    peer = st.session_state.current_peer
    st.session_state.chat.append(entry)
    st.session_state.history.setdefault(peer, []).append(entry)
    save_json(HISTORY_FILE, st.session_state.history)

# Inicializar backend una vez
if 'initialized' not in st.session_state:
    user = st.session_state.nickname
    ip   = get_local_ip()

    # El constructor de Discovery inicia escucha y broadcast
    disc = Discovery(user)
    peers = disc.peers or disc.discover()

    msg = Messaging(
        user,
        on_message=on_msg,
        on_file=on_file,
        udp_sock=disc.sock
    )

    st.session_state.ip           = ip
    st.session_state.discovery    = disc
    st.session_state.peers        = peers
    st.session_state.messaging    = msg
    st.session_state.history      = history
    st.session_state.current_peer = None
    st.session_state.chat         = []
    st.session_state.initialized  = True

# Sidebar: descubrir peers manualmente
if st.sidebar.button("Descubrir Peers"):
    st.session_state.peers = st.session_state.discovery.discover()

# Sidebar: lista de contactos
st.sidebar.markdown("**Contactos:**")
for uid in st.session_state.peers:
    if st.sidebar.button(uid, key=f"peer_{uid}"):
        st.session_state.current_peer = uid
        st.session_state.chat = st.session_state.history.get(uid, []).copy()

# Vista principal del chat
if st.session_state.current_peer:
    peer = st.session_state.current_peer
    st.header(f"Chateando con: **{peer}**")
    for line in st.session_state.chat:
        st.write(line)

    txt = st.text_input("Escribe tu mensaje", key='msg_input')
    if st.button("Enviar"):
        if txt.strip():
            entry = f"[Tú ➤ {peer}] {txt}"
            st.session_state.chat.append(entry)
            st.session_state.history.setdefault(peer, []).append(entry)
            save_json(HISTORY_FILE, st.session_state.history)
            ip = st.session_state.peers[peer]
            st.session_state.messaging.send_message(ip, peer, txt)
        else:
            st.warning("Escribe algo para enviar.")
else:
    st.write("Selecciona un contacto en la barra lateral para iniciar chat.")

# Descargas en sidebar
if DOWNLOADS_DIR.exists():
    st.sidebar.markdown("**Descargas:**")
    for f in sorted(DOWNLOADS_DIR.iterdir()):
        st.sidebar.download_button(label=f.name, data=f.read_bytes(), file_name=f.name)
