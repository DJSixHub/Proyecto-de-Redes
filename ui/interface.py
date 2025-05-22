# ui/interface.py

import os
import sys
import streamlit as st
from datetime import datetime

# --- Ajuste de sys.path para importar core/ y persistence/ ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
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

# 3️⃣ Sidebar: Usuario, IP y acciones
st.sidebar.title(f"Usuario: {user}")
st.sidebar.markdown(
    f"<p style='font-size:12px; color:gray;'>IP: {engine.discovery.local_ip}</p>",
    unsafe_allow_html=True
)
if st.sidebar.button("🔍 Buscar Peers"):
    engine.discovery.force_discover()
    st.sidebar.success("Búsqueda de peers forzada")

# 4️⃣ Construir listas de peers desde discovery
now = datetime.utcnow()
OFFLINE_THRESHOLD = 20.0

raw_peers = engine.discovery.get_peers()  # { raw_uid: {'ip','last_seen'} }

# Mapear UID bytes → display name (sin padding)
name_map = {
    uid: uid.rstrip(b'\x00').decode('utf-8', errors='ignore')
    for uid in raw_peers
}

current_peers = []
previous_peers = []
for uid, info in raw_peers.items():
    name = name_map[uid]
    age = (now - info['last_seen']).total_seconds()
    if age < OFFLINE_THRESHOLD:
        current_peers.append(name)
    else:
        previous_peers.append(name)

# 5️⃣ Dropdowns retornan selección directamente
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

# Determinar peer seleccionado: preferir actual sobre anterior
peer_name = selected_current or selected_previous

# 6️⃣ Mensaje Global
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

# 7️⃣ Chat principal
if peer_name:
    st.header(f"Chateando con: {peer_name}")

    # Conversación histórica con este peer
    conv = engine.history_store.get_conversation(peer_name)
    for entry in conv:
        author = "Yo" if entry['sender'] == user else entry['sender']
        with st.chat_message(author):
            if entry['type'] == 'message':
                st.write(entry['message'])
            else:
                st.write(f"[Archivo] {entry['filename']}")

    # Entrada fija de nuevo mensaje
    new_msg = st.chat_input("Escribe tu mensaje...")
    if new_msg:
        try:
            # Convertir display name a raw UID bytes
            raw_uid = next(uid for uid, name in name_map.items() if name == peer_name)
            engine.messaging.send(raw_uid, new_msg.encode('utf-8'))
            # El st.chat_input provoca rerun automáticamente
        except StopIteration:
            st.error("Peer no encontrado en discovery.")
        except Exception as e:
            st.error(str(e))
else:
    st.write("Selecciona un peer en la barra lateral para comenzar a chatear.")
