import os
import sys
import streamlit as st
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- Ajustar path para importar core/ y persistence/ ---
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
    st.session_state['engine'] = Engine(user_id=user)
engine = st.session_state['engine']

# 3️⃣ Autorefresh para actualizar peers y chat
st_autorefresh(interval=2000, key="refresh")

# 4️⃣ Cargar y decodificar peers
raw_peers = engine.peers_store.load()          # { nombre_str: {'ip','last_seen'} }
name_map  = engine.peers_store.decode_map(raw_peers)  # { nombre_str: uid_bytes }

# 5️⃣ Separar peers actuales / anteriores
now = datetime.utcnow()
OFFLINE_THRESHOLD = 10  # segundos
current_peers, previous_peers = [], []
for name, info in raw_peers.items():
    last = info['last_seen']
    age  = (now - last).total_seconds()
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
            st.sidebar.success("Mensaje global enviado")
        except Exception as e:
            st.sidebar.error(f"Error: {e}")
    else:
        st.sidebar.error("Por favor escribe algo antes de enviar")

# 8️⃣ Área principal de chat
if peer_name:
    st.header(f"Chateando con: {peer_name}")

    # Mostrar conversación histórica
    conv = engine.history_store.get_conversation(peer_name)
    for entry in conv:
        author = "user" if entry['sender'] == user else entry['sender']
        with st.chat_message(author):
            if entry['type'] == 'message':
                st.write(entry['message'])
            else:
                st.write(f"[Archivo] {entry['filename']}")

    # Entrada de nuevo mensaje
    msg = st.chat_input("Escribe tu mensaje...")
    if msg:
        st.session_state["__msg_pending__"] = msg

    # Enviar mensaje pendiente
    if "__msg_pending__" in st.session_state:
        try:
            uid_bytes = name_map[peer_name]
            engine.messaging.send(
                uid_bytes,
                st.session_state["__msg_pending__"].encode('utf-8')
            )
            # Registrar también localmente para verlo en la derecha
            engine.history_store.append_message(
                sender=user,
                recipient=peer_name,
                message=st.session_state["__msg_pending__"],
                timestamp=datetime.utcnow()
            )
            del st.session_state["__msg_pending__"]
        except Exception as e:
            st.error(str(e))

else:
    st.write("Selecciona un peer en la barra lateral para comenzar a chatear.")
