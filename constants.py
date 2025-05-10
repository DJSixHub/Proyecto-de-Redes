
import os

# Forzar bind solo a loopback en Windows para evitar errores de permisos
BIND_ADDR   = os.getenv("LCP_BIND_ADDR", "127.0.0.1")

# Puertos UDP/TCP: se pueden sobreescribir con LCP_UDP_PORT y LCP_TCP_PORT
UDP_PORT    = int(os.getenv("LCP_UDP_PORT", "15000"))
TCP_PORT    = int(os.getenv("LCP_TCP_PORT", "15000"))

# Tamaños de campos en bytes
USERID_SIZE  = 20
OPCODE_SIZE  = 1
BODYID_SIZE  = 1
BODYLEN_SIZE = 8
HEADER_SIZE  = 100  

# Códigos de operación
OP_ECHO = 0   
OP_MSG  = 1   
OP_FILE = 2   

# Response statuses
RESP_OK    = 0
RESP_BAD   = 1
RESP_ERROR = 2

# Timeouts (segundos)
TIMEOUT_SECONDS = 5

# ID special para broadcast 
BROADCAST_ID = b'\xFF' * USERID_SIZE
