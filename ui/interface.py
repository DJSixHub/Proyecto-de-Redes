# ui/interface.py

import os
import sys
import streamlit as st
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- Ajuste de sys.path para importar core/ y persistence/ ---
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.engine import Engine

# 1️⃣ Login de User ID
if 'user_id' not in st.session_state or not st.session_state['user_id']:
    st.title("LCP Chat Interface")
    with st.form("login_form"):
        st.text_input(
            "Ingresa tu User ID (max 20 caracteres):",
            key="input_user_id",
            max_chars=20
        )
        if st.form_submit_button("Confirmar") and st.session_state["input_user_id"]:
            st.session_state['user_id'] = st.session_state["input_user_id"]
    st.stop()

user = st.session_state['user_id']

# 2️⃣ Inicializar Engine
if 'engine' not in st.session_state:
    engine = Engine(user_id=user)
    engine.start()
    st.session_state['engine'] = engine
else:
    engine = st.session_state['engine']

# 3️⃣ Refrescar cada 3 segundos
st_autorefresh(interval=3000, key="auto_refresh")

# 4️⃣ Sidebar
st.sidebar.title(f"Usuario: {user}")
st.sidebar.markdown(
    f"<p style='font-size:12px; color:gray;'>IP: {engine.discovery.local_ip}</p>",
    unsafe_allow_html=True
)
if st.sidebar.button("🔍 Buscar Peers"):
    engine.discovery.force_discover()
    st.sidebar.success("Búsqueda de peers forzada")

# 5️⃣ Peers
now = datetime.utcnow()
OFFLINE_THRESHOLD = 20.0
raw_peers = engine.discovery.get_peers()
name_map = {
    uid: uid.rstrip(b'\x00').decode('utf-8', errors='ignore')
    for uid in raw_peers
}
reverse_map = {v: k for k, v in name_map.items()}

current_peers, previous_peers = [], []
for uid, info in raw_peers.items():
    name = name_map[uid]
    age = (now - info['last_seen']).total_seconds()
    (current_peers if age < OFFLINE_THRESHOLD else previous_peers).append(name)

# 6️⃣ Selección de peer
st.sidebar.subheader("Peers Conectados")
sel_cur = st.sidebar.selectbox("Selecciona un peer actual",
                               sorted(current_peers) or ["Ninguno"])
if sel_cur == "Ninguno": sel_cur = None
st.sidebar.subheader("Peers Anteriores")
sel_prev = st.sidebar.selectbox("Selecciona un peer anterior",
                                sorted(previous_peers) or ["Ninguno"])
if sel_prev == "Ninguno": sel_prev = None

peer_name = sel_cur or sel_prev

# 7️⃣ Mensaje Global
st.sidebar.subheader("Mensaje Global")
msg_global = st.sidebar.text_area("Escribe tu mensaje global aquí:")
if st.sidebar.button("Enviar Mensaje Global"):
    if msg_global:
        try:
            engine.messaging.send_all(msg_global.encode('utf-8'))
            engine.history_store.append_message(
                sender=user,
                recipient="*global*",
                message=msg_global,
                timestamp=datetime.utcnow()
            )
            st.sidebar.success("Mensaje global enviado")
        except Exception as e:
            st.sidebar.error(f"Error: {e}")
    else:
        st.sidebar.error("Escribe algo antes de enviar")

# 8️⃣ Chat con peer
if peer_name:
    st.header(f"Chateando con: {peer_name}")

    # 8.1) Construir conversación (privada + global como privados tuyos)
    private = engine.history_store.get_conversation(peer_name)
    global_msgs = engine.history_store.get_conversation("*global*")
    conv = sorted(private + global_msgs, key=lambda e: e['timestamp'])

    # 8.2) Mostrar con st.chat_message en dos columnas
    for e in conv:
        is_me = (e['sender'] == user)
        left, right = st.columns([3, 3])
        if is_me:
            with right, st.chat_message("user"):
                if e['type'] == 'message':
                    st.write(e['message'])
                else:
                    st.write(f"[Archivo] {e['filename']}")
        else:
            with left, st.chat_message(e['sender']):
                if e['type'] == 'message':
                    st.write(e['message'])
                else:
                    st.write(f"[Archivo] {e['filename']}")

    # 8.3) Enviar texto
    txt = st.chat_input("Escribe tu mensaje...")
    if txt:
        st.session_state["__msg_pending__"] = txt

    if "__msg_pending__" in st.session_state:
        m = st.session_state["__msg_pending__"]
        try:
            uid = reverse_map[peer_name]
            engine.messaging.send(uid, m.encode('utf-8'))
            engine.history_store.append_message(
                sender=user, recipient=peer_name,
                message=m, timestamp=datetime.utcnow()
            )
            left, right = st.columns([3,3])
            with right, st.chat_message("user"):
                st.write(m)
        except Exception as e:
            st.error(str(e))
        finally:
            del st.session_state["__msg_pending__"]

    # 8.4) Enviar archivo
    uploaded = st.file_uploader("Selecciona un archivo para enviar", key="file_uploader")
    if uploaded is not None:
        if st.button("Enviar Archivo"):
            try:
                data = uploaded.read()
                uid = reverse_map[peer_name]
                engine.messaging.send_file(uid, data, uploaded.name)
                engine.history_store.append_file(
                    sender=user, recipient=peer_name,
                    filename=uploaded.name, path=uploaded.name,
                    timestamp=datetime.utcnow()
                )
                left, right = st.columns([3,3])
                with right, st.chat_message("user"):
                    st.write(f"[Archivo] {uploaded.name}")
            except Exception as e:
                st.error(str(e))

else:
    st.write("Selecciona un peer en la barra lateral para comenzar a chatear.")
