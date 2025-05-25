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

# 3️⃣ Refrescar cada 3 segundos (para recibir mensajes automáticamente)
st_autorefresh(interval=3000, key="auto_refresh")

# 4️⃣ Sidebar: Usuario, IP y acciones
st.sidebar.title(f"Usuario: {user}")
st.sidebar.markdown(
    f"<p style='font-size:12px; color:gray;'>IP: {engine.discovery.local_ip}</p>",
    unsafe_allow_html=True
)
if st.sidebar.button("🔍 Buscar Peers"):
    engine.discovery.force_discover()
    st.sidebar.success("Búsqueda de peers forzada")

# 5️⃣ Cargar peers actuales y anteriores
now = datetime.utcnow()
OFFLINE_THRESHOLD = 20.0

# raw_peers: { uid_bytes: {'ip','last_seen'} }
raw_peers = engine.discovery.get_peers()

# name_map: uid_bytes -> nombre_str limpio
name_map = {
    uid: uid.rstrip(b'\x00').decode('utf-8', errors='ignore')
    for uid in raw_peers
}
# reverse_map: nombre_str -> uid_bytes
reverse_map = {name: uid for uid, name in name_map.items()}

current_peers = []
previous_peers = []
for uid, info in raw_peers.items():
    name = name_map[uid]
    age = (now - info['last_seen']).total_seconds()
    if age < OFFLINE_THRESHOLD:
        current_peers.append(name)
    else:
        previous_peers.append(name)

# 6️⃣ Selección de peer
st.sidebar.subheader("Peers Conectados")
selected_current = st.sidebar.selectbox(
    "Selecciona un peer actual",
    sorted(current_peers) if current_peers else ["Ninguno"]
)
if selected_current == "Ninguno":
    selected_current = None

st.sidebar.subheader("Peers Anteriores")
selected_previous = st.sidebar.selectbox(
    "Selecciona un peer anterior",
    sorted(previous_peers) if previous_peers else ["Ninguno"]
)
if selected_previous == "Ninguno":
    selected_previous = None

peer_name = selected_current or selected_previous

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
        st.sidebar.error("Por favor escribe algo antes de enviar")

# 8️⃣ Envío de archivos (Sidebar)
st.sidebar.subheader("Enviar Archivo")
if peer_name:
    uploaded = st.sidebar.file_uploader("Selecciona un archivo", key="file_uploader")
    if uploaded is not None and st.sidebar.button("Enviar Archivo"):
        try:
            data = uploaded.read()
            uid_bytes = reverse_map[peer_name]
            engine.messaging.send_file(uid_bytes, data, uploaded.name)
            # append_file sólo necesita sender, recipient, filename, timestamp
            engine.history_store.append_file(
                sender=user,
                recipient=peer_name,
                filename=uploaded.name,
                timestamp=datetime.utcnow()
            )
            st.sidebar.success(f"Archivo '{uploaded.name}' enviado")
        except Exception as e:
            st.sidebar.error(str(e))
else:
    st.sidebar.info("Selecciona un peer para enviar archivos")

# 9️⃣ Área principal de chat
if peer_name:
    st.header(f"Chateando con: {peer_name}")

    # 9.1) Mensajes privados + globales (como tuyos)
    private = engine.history_store.get_conversation(peer_name)
    global_msgs = engine.history_store.get_conversation("*global*")
    conv = sorted(private + global_msgs, key=lambda e: e['timestamp'])

    # 9.2) Mostrar con st.chat_message en dos columnas
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

    # 9.3) Enviar nuevo mensaje de texto
    txt = st.chat_input("Escribe tu mensaje...")
    if txt:
        st.session_state["__msg_pending__"] = txt

    if "__msg_pending__" in st.session_state:
        m = st.session_state["__msg_pending__"]
        try:
            uid_bytes = reverse_map[peer_name]
            engine.messaging.send(uid_bytes, m.encode('utf-8'))
            engine.history_store.append_message(
                sender=user,
                recipient=peer_name,
                message=m,
                timestamp=datetime.utcnow()
            )
            left, right = st.columns([3, 3])
            with right, st.chat_message("user"):
                st.write(m)
        except Exception as e:
            st.error(str(e))
        finally:
            del st.session_state["__msg_pending__"]

else:
    st.write("Selecciona un peer en la barra lateral para comenzar a chatear.")
