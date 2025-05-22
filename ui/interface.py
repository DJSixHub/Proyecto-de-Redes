# ui/interface.py

import os
import sys
import streamlit as st
from datetime import datetime

# Ajustar sys.path para importar core/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.engine import Engine

# 1️⃣ Login de User ID
if 'user_id' not in st.session_state or not st.session_state['user_id']:
    st.title("LCP Chat Interface")
    with st.form("login_form"):
        st.text_input("Ingresa tu User ID (max 20 caracteres):",
                      key="input_user_id", max_chars=20)
        if st.form_submit_button("Confirmar") and st.session_state["input_user_id"]:
            st.session_state['user_id'] = st.session_state["input_user_id"]
    st.stop()

user = st.session_state['user_id']

# 2️⃣ Arrancar Engine
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

# 4️⃣ Construir listas de peers
OFFLINE_THRESHOLD = 20.0
now = datetime.utcnow()
raw_peers = engine.discovery.get_peers()  # raw_id_bytes → {'ip','last_seen'}

# Mapear raw_id_bytes ↔ display name (sin padding)
name_map = {
    raw: raw.rstrip(b'\x00').decode('utf-8', errors='ignore')
    for raw in raw_peers
}
reverse_map = {v: k for k, v in name_map.items()}

current_peers = []
previous_peers = []
for raw_id, info in raw_peers.items():
    name = name_map[raw_id]
    age = (now - info['last_seen']).total_seconds()
    if age < OFFLINE_THRESHOLD:
        current_peers.append(name)
    else:
        previous_peers.append(name)

# 5️⃣ Selección de peer
if 'selected_peer' not in st.session_state:
    st.session_state['selected_peer'] = (current_peers or previous_peers or [None])[0]

def on_select_current():
    st.session_state['selected_peer'] = st.session_state['current_dropdown']

def on_select_previous():
    st.session_state['selected_peer'] = st.session_state['previous_dropdown']

st.sidebar.subheader("Peers Conectados")
if current_peers:
    st.sidebar.selectbox(
        "Selecciona un peer actual",
        current_peers,
        key='current_dropdown',
        on_change=on_select_current
    )
else:
    st.sidebar.write("Ninguno")

st.sidebar.subheader("Peers Anteriores")
if previous_peers:
    st.sidebar.selectbox(
        "Selecciona un peer anterior",
        previous_peers,
        key='previous_dropdown',
        on_change=on_select_previous
    )
else:
    st.sidebar.write("Ninguno")

# 6️⃣ Mensaje Global
st.sidebar.subheader("Mensaje Global")
msg_global = st.sidebar.text_area(
    "Escribe tu mensaje global aquí:",
    key="global_message_input"
)
if st.sidebar.button("Enviar Mensaje Global"):
    if msg_global:
        try:
            engine.messaging.send_all(msg_global.encode('utf-8'))
            st.sidebar.success("Mensaje global enviado")
        except Exception as e:
            st.sidebar.error(f"Error: {e}")
    else:
        st.sidebar.error("Por favor escribe algo")

# 7️⃣ Chat principal
peer_name = st.session_state['selected_peer']
if peer_name:
    st.header(f"Chateando con: {peer_name}")

    # Recuperar conversación con este peer
    conv = engine.history_store.get_conversation(peer_name)
    for entry in conv:
        author = entry['sender']
        with st.chat_message(author):
            if entry['type'] == 'message':
                st.write(entry['message'])
            else:
                st.write(f"[Archivo] {entry['filename']}")

    # Entrada fija de mensaje
    msg = st.chat_input("Escribe tu mensaje...")
    if msg:
        try:
            raw_id = reverse_map[peer_name]
            engine.messaging.send(
                raw_id,
                msg.encode('utf-8')
            )
        except Exception as e:
            st.error(str(e))
else:
    st.write("Selecciona un peer en la barra lateral para comenzar a chatear.")
