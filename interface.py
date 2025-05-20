import streamlit as st
import json
from pathlib import Path
from util import get_local_ip
from discovery import Discovery
from messaging import Messaging

# Persistencia
SETTINGS_FILE = Path('settings.json')
HISTORY_FILE  = Path('chat_history.json')
DOWNLOADS_DIR = Path('Descargas')

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

# Sesión: nickname
if 'nickname' not in st.session_state:
    st.session_state.nickname     = settings.get('nickname')
    st.session_state.editing_nick = False
    st.session_state.new_nick     = st.session_state.nickname or ''

# Sidebar: usuario & cambiar nickname
st.sidebar.markdown(f"### Usuario: **{st.session_state.nickname or '—'}**")
if not st.session_state.editing_nick:
    if st.sidebar.button("Cambiar Nickname"):
        st.session_state.editing_nick = True
if st.session_state.editing_nick:
    st.session_state.new_nick = st.sidebar.text_input(
        "Nuevo nickname", value=st.session_state.new_nick, key='nick_input'
    )
    if st.sidebar.button("OK", key='ok_nick'):
        st.session_state.nickname = st.session_state.new_nick
        settings['nickname'] = st.session_state.new_nick
        save_json(SETTINGS_FILE, settings)
        st.session_state.editing_nick = False

if not st.session_state.nickname:
    st.sidebar.warning("Define tu nickname para continuar.")
    st.stop()

# Callbacks para mensajes y archivos
def on_msg(from_id, message):
    peer = st.session_state.current_peer
    st.session_state.chat.append(('other', f"[{from_id}] {message}"))
    history.setdefault(peer, []).append(('other', f"[{from_id}] {message}"))
    save_json(HISTORY_FILE, history)

def on_file(from_id, data):
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    fname = DOWNLOADS_DIR / f"{from_id}_{len(data)}.bin"
    fname.write_bytes(data)
    st.session_state.chat.append(('other', f"[Archivo de {from_id}] {fname.name}"))
    history.setdefault(st.session_state.current_peer, []).append(('other', f"[Archivo de {from_id}] {fname.name}"))
    save_json(HISTORY_FILE, history)

# Inicializar backend una vez
if 'initialized' not in st.session_state:
    user = st.session_state.nickname
    ip   = get_local_ip()
    disc = Discovery(user)
    msg  = Messaging(user, on_message=on_msg, on_file=on_file, udp_sock=disc.sock)
    st.session_state.ip           = ip
    st.session_state.discovery    = disc
    st.session_state.peers        = disc.peers
    st.session_state.messaging    = msg
    st.session_state.history      = history
    st.session_state.current_peer = None
    st.session_state.chat         = []
    st.session_state.initialized  = True

# Sidebar: Buscar Peers
if st.sidebar.button("Buscar Peers"):
    st.session_state.peers = st.session_state.discovery.discover()

# Sidebar: contactos dinámicos
st.sidebar.markdown("**Contactos:**")
for uid in st.session_state.peers:
    if st.sidebar.button(uid, key=f"peer_{uid}"):
        st.session_state.current_peer = uid
        st.session_state.chat = st.session_state.history.get(uid, []).copy()

# Vista principal del chat
if st.session_state.current_peer:
    peer = st.session_state.current_peer
    st.header(f"Chateando con: **{peer}**")

    # Mensajes alineados
    for who, text in st.session_state.chat:
        left, right = st.columns([3,1]) if who=='other' else st.columns([1,3])
        if who=='other':
            left.write(text); right.write("")
        else:
            left.write(""); right.write(text)

    # Entrada fija al pie
    txt = st.text_input("Mensaje", key='msg_input')
    if st.button("Enviar"):
        if txt.strip():
            st.session_state.chat.append(('me', f"[Tú] {txt}"))
            history.setdefault(peer, []).append(('me', f"[Tú] {txt}"))
            save_json(HISTORY_FILE, history)
            ip_target = st.session_state.peers[peer]
            st.session_state.messaging.send_message(ip_target, peer, txt)
            st.experimental_rerun()
        else:
            st.warning("Escribe algo para enviar.")
else:
    st.write("Selecciona un contacto en la barra lateral para iniciar chat.")

# Sidebar: descargas
if DOWNLOADS_DIR.exists():
    st.sidebar.markdown("**Descargas:**")
    for f in sorted(DOWNLOADS_DIR.iterdir()):
        st.sidebar.download_button(label=f.name, data=f.read_bytes(), file_name=f.name)
