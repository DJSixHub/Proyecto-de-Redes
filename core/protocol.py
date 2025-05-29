# core/protocol.py

import struct

# Puertos por defecto
UDP_PORT = 9990
TCP_PORT = 9990

# Tamaños de campos según especificación
USER_ID_SIZE = 20
OP_CODE_SIZE = 1
BODY_ID_SIZE = 1
BODY_LENGTH_SIZE = 8
HEADER_RESERVED_SIZE = 50
RESPONSE_RESERVED_SIZE = 4

# Tamaño fijo de la cabecera según especificación:
# UserIdFrom(20) + UserIdTo(20) + OperationCode(1) + BodyId(1) + BodyLength(8) + Reserved(50) = 100 bytes
HEADER_SIZE = USER_ID_SIZE + USER_ID_SIZE + OP_CODE_SIZE + BODY_ID_SIZE + BODY_LENGTH_SIZE + HEADER_RESERVED_SIZE

# Tamaño fijo de respuesta según especificación:
# ResponseStatus(1) + ResponseId(20) + Reserved(4) = 25 bytes
RESPONSE_SIZE = OP_CODE_SIZE + USER_ID_SIZE + RESPONSE_RESERVED_SIZE

# UID de broadcast (20 bytes de 0xFF)
BROADCAST_UID = b'\xff' * USER_ID_SIZE

# Formato de respuesta
RESPONSE_FMT = '!B20s4x'  # status(1) + responder(20) + padding(4)

# Códigos de operación
OP_ECHO = 0
OP_MESSAGE = 1
OP_FILE = 2

# Códigos de respuesta
RESP_OK = 0
RESP_BAD_REQUEST = 1
RESP_INTERNAL_ERROR = 2

def pack_header(user_from: bytes,
                user_to: bytes = BROADCAST_UID,
                op_code: int = OP_ECHO,
                body_id: int = 0,
                body_len: int = 0) -> bytes:
    """
    Empaqueta un header según especificación LCP (100 bytes):
      0–19   user_from   (20 bytes, UTF-8)
     20–39   user_to     (20 bytes, UTF-8, 0xFF...FF para broadcast)
        40   op_code     (1 byte: 0=Echo, 1=Message, 2=File)
        41   body_id     (1 byte: ID único para mensajes multi-parte)
     42–49   body_len    (8 bytes, big-endian)
     50–99   reserved    (50 bytes, ceros)
    """
    if not isinstance(user_from, bytes) or not isinstance(user_to, bytes):
        raise ValueError("user_from y user_to deben ser bytes")
    if op_code not in (OP_ECHO, OP_MESSAGE, OP_FILE):
        raise ValueError(f"op_code inválido: {op_code}")
    if not 0 <= body_id <= 255:
        raise ValueError(f"body_id debe estar entre 0 y 255")
    if not 0 <= body_len <= (2**64 - 1):
        raise ValueError(f"body_len fuera de rango")

    header = bytearray(HEADER_SIZE)
    
    # UserIdFrom y UserIdTo: asegurar 20 bytes exactos
    header[0:USER_ID_SIZE] = user_from.ljust(USER_ID_SIZE, b'\x00')[:USER_ID_SIZE]
    header[USER_ID_SIZE:2*USER_ID_SIZE] = user_to.ljust(USER_ID_SIZE, b'\x00')[:USER_ID_SIZE]
    
    # Operation Code y Body ID: 1 byte cada uno
    header[40] = op_code
    header[41] = body_id
    
    # Body Length: 8 bytes big-endian
    header[42:50] = body_len.to_bytes(BODY_LENGTH_SIZE, 'big')
    
    # Reserved: ya está en ceros
    return bytes(header)

def unpack_header(data: bytes) -> dict:
    """
    Desempaqueta un header LCP y valida sus campos.
    Devuelve dict con user_from, user_to, op_code, body_id, body_len.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Header demasiado corto: {len(data)} bytes (esperado {HEADER_SIZE})")
        
    h = data[:HEADER_SIZE]
    
    op_code = h[40]
    if op_code not in (OP_ECHO, OP_MESSAGE, OP_FILE):
        raise ValueError(f"op_code inválido: {op_code}")
        
    return {
        'user_from': h[0:USER_ID_SIZE].rstrip(b'\x00'),
        'user_to': h[USER_ID_SIZE:2*USER_ID_SIZE].rstrip(b'\x00'),
        'op_code': op_code,
        'body_id': h[41],
        'body_len': int.from_bytes(h[42:50], 'big')
    }

def pack_response(status: int, responder: bytes) -> bytes:
    """
    Empaqueta una respuesta según especificación LCP (25 bytes):
      0      status      (1 byte: 0=OK, 1=Bad Request, 2=Internal Error)
      1-20   responder   (20 bytes, UTF-8)
     21-24   reserved    (4 bytes, ceros)
    """
    if status not in (RESP_OK, RESP_BAD_REQUEST, RESP_INTERNAL_ERROR):
        raise ValueError(f"status inválido: {status}")
    if not isinstance(responder, bytes):
        raise ValueError("responder debe ser bytes")
        
    # Asegurar que responder tenga exactamente 20 bytes
    resp_id = responder.ljust(USER_ID_SIZE, b'\x00')[:USER_ID_SIZE]
    
    return struct.pack(RESPONSE_FMT, status, resp_id)

def unpack_response(data: bytes) -> dict:
    """
    Desempaqueta una respuesta LCP y valida sus campos.
    Devuelve dict con status y responder.
    """
    if len(data) < RESPONSE_SIZE:
        raise ValueError(f"Response demasiado corto: {len(data)} bytes (esperado {RESPONSE_SIZE})")
        
    status, responder = struct.unpack('!B20s', data[:21])
    
    if status not in (RESP_OK, RESP_BAD_REQUEST, RESP_INTERNAL_ERROR):
        raise ValueError(f"status inválido: {status}")
        
    return {
        'status': status,
        'responder': responder.rstrip(b'\x00')
    }

def pack_message_body(body_id: int, message: bytes) -> bytes:
    """
    Empaqueta el cuerpo de un mensaje según especificación LCP:
      0-7     message_id  (8 bytes, matching body_id)
      8-      content     (UTF-8 message)
    """
    if not 0 <= body_id <= 255:
        raise ValueError("body_id debe estar entre 0 y 255")
    
    return body_id.to_bytes(8, 'big') + message

def unpack_message_body(data: bytes) -> tuple:
    """
    Desempaqueta el cuerpo de un mensaje.
    Devuelve (message_id, content).
    """
    if len(data) < 8:
        raise ValueError("Cuerpo de mensaje demasiado corto")
        
    message_id = int.from_bytes(data[:8], 'big')
    content = data[8:]
    return message_id, content
