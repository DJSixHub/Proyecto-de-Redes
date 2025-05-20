import streamlit as st
import json
from pathlib import Path
from util import get_local_ip
from discovery import Discovery
from messaging import Messaging

SETTINGS_FILE = Path('settings.json')
HISTORY_FILE  = Path('chat_history.json')
DOWNLOADS_DIR = Path('Descargas')

def load_json(p, default):
    if p.exists():
        return json.loads(p.read_text())
    p.write_text(json.dumps(default))
    return default

def save_json(p, data):
    p.write_text(json.dumps(data))

settings = load_json(SETTINGS_FILE, {'nickname': None})
history  = load_json(HISTORY_FILE, {})

if 'nickname' not in st.session_state:
    st.session_state.nickname     = settings['nickname']
    st.session_state.editing_nick = False
    st.session_state.new_nick     = settings['nickname'] or ''

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
else:
    if 'initialized' not in st.session_state:
        user = st.session_state.nickname
        ip   = get_local_ip()
        disc = Discovery(user)
        msg  = Messaging(user, on_message=lambda f,m: on_msg(f,m),
                               on_file=lambda f,d: on_file(f,d),
                               udp_sock=disc.sock)
        st.session_state.discovery    = disc
        st.session_state.peers        = disc.peers
        st.session_state.messaging    = msg
        st.session_state.history      = history
        st.session_state.current_peer = None
        st.session_state.chat         = []
        st.session_state.initialized  = True

    if st.sidebar.button("Buscar Peers"):
        st.session_state.peers = st.session_state.discovery.discover()

    st.sidebar.markdown("**Contactos:**")
    for uid in st.session_state.peers:
        if st.sidebar.button(uid, key=f"peer_{uid}"):
            st.session_state.current_peer = uid
            st.session_state.chat = st.session_state.history.get(uid, [])

    if st.session_state.current_peer:
        peer = st.session_state.current_peer
        st.header(f"Chateando con: **{peer}**")

        for who, txt in st.session_state.chat:
            left, right = st.columns([3,1]) if who=='other' else st.columns([1,3])
            if who=='other':
                left.write(txt)
            else:
                right.write(txt)

        msg_input = st.text_input("Mensaje", key='msg_input')
        if st.button("Enviar"):
            if msg_input:
                entry = ('me', f"[Tú] {msg_input}")
                st.session_state.chat.append(entry)
                st.session_state.history.setdefault(peer, []).append(entry)
                save_json(HISTORY_FILE, st.session_state.history)
                ipt = st.session_state.peers[peer]
                st.session_state.messaging.send_message(ipt, peer, msg_input)
    else:
        st.write("Selecciona un contacto para iniciar chat.")

    if DOWNLOADS_DIR.exists():
        st.sidebar.markdown("**Descargas:**")
        for f in sorted(DOWNLOADS_DIR.iterdir()):
            st.sidebar.download_button(label=f.name, data=f.read_bytes(), file_name=f.name)

def on_msg(from_id, message):
    peer = st.session_state.current_peer
    e = ('other', f"[{from_id}] {message}")
    st.session_state.chat.append(e)
    st.session_state.history.setdefault(peer, []).append(e)
    save_json(HISTORY_FILE, st.session_state.history)

def on_file(from_id, data):
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    fn = DOWNLOADS_DIR / f"{from_id}_{len(data)}.bin"
    fn.write_bytes(data)
    e = ('other', f"[Archivo de {from_id}] {fn.name}")
    st.session_state.chat.append(e)
    st.session_state.history.setdefault(st.session_state.current_peer, []).append(e)
    save_json(HISTORY_FILE, st.session_state.history)
