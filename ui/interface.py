# ui/interface.py

import os
import sys
import streamlit as st
from datetime import datetime, UTC
from streamlit_autorefresh import st_autorefresh

# Este archivo implementa la interfaz gráfica del chat utilizando Streamlit. El flujo de la aplicación
# comienza con la autenticación del usuario mediante un ID, luego inicializa el motor de comunicación
# que maneja las conexiones P2P. La interfaz se actualiza automáticamente cada 3 segundos y muestra
# una barra lateral con información del usuario y controles, mientras que el área principal muestra
# las conversaciones. El sistema permite enviar mensajes privados, mensajes globales y archivos,
# manteniendo un registro del historial de comunicaciones y el estado de los peers conectados.

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.engine import Engine

# Constantes
OFFLINE_THRESHOLD = 20.0  # segundos
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB máximo para archivos
REFRESH_INTERVAL = 3000  # ms

# Maneja la autenticación del usuario solicitando un ID único que se almacenará
# en la sesión. Es necesario para identificar al usuario en la red P2P.
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

# Inicializa el motor de comunicación P2P si no existe en la sesión actual.
# Este componente es crucial para manejar la comunicación entre peers.
if 'engine' not in st.session_state:
    try:
        engine = Engine(user_id=user)
        engine.start()
        st.session_state['engine'] = engine
    except Exception as e:
        st.error(f"Error al inicializar el chat: {e}")
        st.stop()
else:
    engine = st.session_state['engine']

# Configura el refresco automático de la interfaz para mantener
# la información actualizada sin intervención del usuario
st_autorefresh(interval=REFRESH_INTERVAL, key="auto_refresh")

# Configura la barra lateral con información del usuario y controles de conexión.
# Muestra el estado de la conexión TCP y permite buscar nuevos peers.
st.sidebar.title(f"Usuario: {user}")
st.sidebar.markdown(
    f"<p style='font-size:12px; color:gray;'>IP: {engine.discovery.local_ip}</p>",
    unsafe_allow_html=True
)

# Estado de la conexión TCP
tcp_status = "🟢 TCP Activo" if engine.messaging.tcp_sock else "🔴 TCP Inactivo"
st.sidebar.markdown(f"<p style='font-size:12px;'>{tcp_status}</p>", unsafe_allow_html=True)

if st.sidebar.button("🔍 Buscar Peers"):
    with st.sidebar.status("Buscando peers..."):
        engine.discovery.force_discover()
        st.sidebar.success("Búsqueda de peers completada")

# Procesa y organiza la información de los peers conectados y anteriores
# para su visualización en la interfaz
now = datetime.now(UTC)

raw_peers = engine.discovery.get_peers()  # keys uid_bytes or uid_str → {'ip','last_seen'}

# Unificar: lista de tuples (name_str, uid_bytes, info)
peers = []
for uid_key, info in raw_peers.items():
    if isinstance(uid_key, bytes):
        trimmed = uid_key.rstrip(b'\x00')
        name_str = trimmed.decode('utf-8', errors='ignore')
        uid_bytes = trimmed.ljust(20, b'\x00')
    else:
        name_str = uid_key
        b = name_str.encode('utf-8')
        trimmed = b[:20]
        uid_bytes = trimmed.ljust(20, b'\x00')
    peers.append((name_str, uid_bytes, info))

# reverse_map: name_str → uid_bytes
reverse_map = {name: uid for name, uid, _ in peers}

# Separar actuales / anteriores por last_seen
current_peers = [
    name for name, _, info in peers
    if (now - info['last_seen']).total_seconds() < OFFLINE_THRESHOLD
]
previous_peers = [
    name for name, _, info in peers
    if (now - info['last_seen']).total_seconds() >= OFFLINE_THRESHOLD
]

# Implementa la selección de peers para el chat, permitiendo elegir
# entre peers actuales y anteriores
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

# Implementa la funcionalidad de mensajes globales que se envían
# a todos los peers conectados
st.sidebar.subheader("Mensaje Global")
msg_global = st.sidebar.text_area("Escribe tu mensaje global aquí:")
if st.sidebar.button("Enviar Mensaje Global"):
    if msg_global:
        with st.sidebar.status("Enviando mensaje global..."):
            try:
                engine.messaging.send_all(msg_global.encode('utf-8'))
                engine.history_store.append_message(
                    sender=user,
                    recipient="*global*",
                    message=msg_global,
                    timestamp=datetime.now(UTC)
                )
                st.sidebar.success("Mensaje global enviado")
            except Exception as e:
                st.sidebar.error(f"Error al enviar mensaje global: {e}")
    else:
        st.sidebar.error("Por favor escribe algo antes de enviar")

# Maneja la funcionalidad de envío de archivos, incluyendo validaciones
# de tamaño y gestión de errores
st.sidebar.subheader("Enviar Archivo")
if peer_name:
    uploaded = st.sidebar.file_uploader(
        "Selecciona un archivo",
        key="file_uploader",
        help=f"Tamaño máximo: {MAX_UPLOAD_SIZE/1024/1024:.1f} MB"
    )
    
    if uploaded is not None:
        file_size = len(uploaded.getvalue())
        if file_size > MAX_UPLOAD_SIZE:
            st.sidebar.error(f"Archivo demasiado grande ({file_size/1024/1024:.1f} MB)")
        elif st.sidebar.button("Enviar Archivo"):
            with st.sidebar.status(f"Enviando archivo {uploaded.name}...") as status:
                try:
                    data = uploaded.getvalue()
                    uid_bytes = reverse_map[peer_name]
                    
                    status.update(label="Estableciendo conexión TCP...")
                    engine.messaging.send_file(uid_bytes, data, uploaded.name)
                    
                    engine.history_store.append_file(
                        sender=user,
                        recipient=peer_name,
                        filename=uploaded.name,
                        timestamp=datetime.now(UTC)
                    )
                    st.sidebar.success(f"Archivo '{uploaded.name}' enviado correctamente")
                except ConnectionError as e:
                    st.sidebar.error(f"Error de conexión: {e}")
                except TimeoutError as e:
                    st.sidebar.error(f"Timeout al enviar archivo: {e}")
                except Exception as e:
                    st.sidebar.error(f"Error al enviar archivo: {e}")
else:
    st.sidebar.info("Selecciona un peer para enviar archivos")

# Implementa el área principal de chat mostrando mensajes globales
# y conversaciones privadas
st.header("Chat")

# Muestra los mensajes globales en el área principal
st.subheader("Mensajes Globales")
global_msgs = engine.history_store.get_conversation("*global*")
for e in global_msgs:
    is_me = (e['sender'] == user)
    left, right = st.columns([3, 3])
    if is_me:
        with right, st.chat_message("user"):
            st.write(f"[Global] {e['message']}")
    else:
        with left, st.chat_message(e['sender']):
            st.write(f"[Global] {e['message']}")

# Muestra la conversación privada con el peer seleccionado
if peer_name:
    st.subheader(f"Chat con {peer_name}")
    private = engine.history_store.get_conversation(peer_name)
    
    # Filtrar mensajes globales que ya mostramos arriba
    private = [msg for msg in private if msg.get('recipient') != "*global*"]
    
    for e in private:
        is_me = (e['sender'] == user)
        left, right = st.columns([3, 3])
        if is_me:
            with right, st.chat_message("user"):
                if e['type'] == 'message':
                    st.write(e['message'])
                else:
                    st.write(f"[Archivo] {e['filename']}")
                    # Mostrar estado de transferencia si es reciente
                    if (now - e['timestamp']).total_seconds() < 30:
                        st.caption("✅ Transferido por TCP")
        else:
            with left, st.chat_message(e['sender']):
                if e['type'] == 'message':
                    st.write(e['message'])
                else:
                    st.write(f"[Archivo] {e['filename']}")
                    if (now - e['timestamp']).total_seconds() < 30:
                        st.caption("✅ Transferido por TCP")

    # 9.3) Enviar mensaje de texto
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
                timestamp=datetime.now(UTC)
            )
            left, right = st.columns([3, 3])
            with right, st.chat_message("user"):
                st.write(m)
        except ConnectionError as e:
            st.error(f"Error de conexión: {e}")
        except TimeoutError as e:
            st.error(f"Timeout al enviar mensaje: {e}")
        except Exception as e:
            st.error(f"Error al enviar mensaje: {e}")
        finally:
            del st.session_state["__msg_pending__"]

else:
    st.write("Selecciona un peer en la barra lateral para comenzar a chatear.")
