# core/protocol.py

# Implementación del protocolo LCP (Local Chat Protocol)
# Define serialización/deserialización de mensajes con cabecera de 100 bytes,
# cuerpo variable y respuestas de 25 bytes para comunicación entre peers

import struct

# Puertos para comunicación
UDP_PORT = 9990  # Puerto para descubrimiento
TCP_PORT = 9990  # Puerto para mensajes y archivos

# Tamaños de campos del protocolo
USER_ID_SIZE = 20         # ID de usuario
OP_CODE_SIZE = 1          # Código de operación
BODY_ID_SIZE = 1          # ID de cuerpo
BODY_LENGTH_SIZE = 8      # Longitud de cuerpo
HEADER_RESERVED_SIZE = 50 # Reservado cabecera
RESPONSE_RESERVED_SIZE = 4 # Reservado respuesta

# Estructura de cabecera (100 bytes):
# - UserIdFrom (20B): ID remitente
# - UserIdTo (20B): ID destinatario
# - OperationCode (1B): Tipo operación
# - BodyId (1B): ID cuerpo
# - BodyLength (8B): Longitud cuerpo
# - Reserved (50 bytes): Espacio reservado para futuras extensiones
HEADER_SIZE = USER_ID_SIZE + USER_ID_SIZE + OP_CODE_SIZE + BODY_ID_SIZE + BODY_LENGTH_SIZE + HEADER_RESERVED_SIZE

# Cálculo del tamaño total de la respuesta (25 bytes)
# La estructura es:
# - ResponseStatus (1 byte): Estado de la respuesta
# - ResponseId (20 bytes): Identificador del respondedor
# - Reserved (4 bytes): Espacio reservado
RESPONSE_SIZE = OP_CODE_SIZE + USER_ID_SIZE + RESPONSE_RESERVED_SIZE

# Identificador especial para mensajes de broadcast
# Se usa FF como valor para indicar envío a todos los peers
BROADCAST_UID = b'\xff' * USER_ID_SIZE

# Formato de empaquetado para respuestas usando struct
# !: usar orden de bytes de red (big-endian)
# B: unsigned char (1 byte) para status
# 20s: string de 20 bytes para responder
# 4x: 4 bytes de padding
RESPONSE_FMT = '!B20s4x'

# Códigos de operación soportados por el protocolo
OP_ECHO = 0    # Operación de eco para verificar conectividad
OP_MESSAGE = 1 # Operación de envío de mensaje de texto
OP_FILE = 2    # Operación de envío de archivo

# Códigos de estado para las respuestas
RESP_OK = 0             # Operación exitosa
RESP_BAD_REQUEST = 1    # Error en la solicitud
RESP_INTERNAL_ERROR = 2 # Error interno del servidor

# Empaqueta los campos de la cabecera en una secuencia de bytes
# Esta función es crítica porque:
# 1. Valida todos los campos de entrada
# 2. Asegura el tamaño correcto de cada campo
# 3. Mantiene el orden de bytes especificado
def pack_header(user_from: bytes,
                user_to: bytes = BROADCAST_UID,
                op_code: int = OP_ECHO,
                body_id: int = 0,
                body_len: int = 0) -> bytes:
    if not isinstance(user_from, bytes) or not isinstance(user_to, bytes):
        raise ValueError("user_from y user_to deben ser bytes")
    if op_code not in (OP_ECHO, OP_MESSAGE, OP_FILE):
        raise ValueError(f"op_code inválido: {op_code}")
    if not 0 <= body_id <= 255:
        raise ValueError(f"body_id debe estar entre 0 y 255")
    if not 0 <= body_len <= (2**64 - 1):
        raise ValueError(f"body_len fuera de rango")

    header = bytearray(HEADER_SIZE)
    
    # Procesamiento de identificadores: aseguramos exactamente 20 bytes
    # Se usa relleno con null bytes si es necesario
    header[0:USER_ID_SIZE] = user_from.ljust(USER_ID_SIZE, b'\x00')[:USER_ID_SIZE]
    header[USER_ID_SIZE:2*USER_ID_SIZE] = user_to.ljust(USER_ID_SIZE, b'\x00')[:USER_ID_SIZE]
    
    # Códigos de operación y cuerpo: 1 byte cada uno
    header[40] = op_code
    header[41] = body_id
    
    # Longitud del cuerpo: 8 bytes en big-endian
    header[42:50] = body_len.to_bytes(BODY_LENGTH_SIZE, 'big')
    
    return bytes(header)

# Desempaqueta y valida una cabecera recibida
# Esta función es esencial porque:
# 1. Verifica la integridad de los datos recibidos
# 2. Extrae los campos en formato utilizable
# 3. Valida los valores de los campos
def unpack_header(data: bytes) -> dict:
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Header demasiado corto: {len(data)} bytes (esperado {HEADER_SIZE})")
        
    h = data[:HEADER_SIZE]
    
    # Validación del código de operación
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

# Empaqueta una respuesta según el protocolo
# Esta función es importante porque:
# 1. Valida el estado de la respuesta
# 2. Asegura el formato correcto del identificador
# 3. Mantiene la estructura de 25 bytes
def pack_response(status: int, responder: bytes) -> bytes:
    if status not in (RESP_OK, RESP_BAD_REQUEST, RESP_INTERNAL_ERROR):
        raise ValueError(f"status inválido: {status}")
    if not isinstance(responder, bytes):
        raise ValueError("responder debe ser bytes")
        
    # Aseguramos que el identificador tenga exactamente 20 bytes
    resp_id = responder.ljust(USER_ID_SIZE, b'\x00')[:USER_ID_SIZE]
    
    return struct.pack(RESPONSE_FMT, status, resp_id)

# Desempaqueta y valida una respuesta recibida
# Esta función es necesaria porque:
# 1. Verifica el tamaño correcto de la respuesta
# 2. Valida el código de estado
# 3. Extrae el identificador del respondedor
def unpack_response(data: bytes) -> dict:
    if len(data) < RESPONSE_SIZE:
        raise ValueError(f"Response demasiado corto: {len(data)} bytes (esperado {RESPONSE_SIZE})")
        
    status, responder = struct.unpack('!B20s', data[:21])
    
    if status not in (RESP_OK, RESP_BAD_REQUEST, RESP_INTERNAL_ERROR):
        raise ValueError(f"status inválido: {status}")
        
    return {
        'status': status,
        'responder': responder.rstrip(b'\x00')
    }

# Empaqueta el cuerpo de un mensaje
# Esta función es importante porque:
# 1. Valida el ID del cuerpo
# 2. Combina el ID con el contenido
# 3. Mantiene el formato especificado
def pack_message_body(body_id: int, message: bytes) -> bytes:
    if not 0 <= body_id <= 255:
        raise ValueError("body_id debe estar entre 0 y 255")
    
    return body_id.to_bytes(8, 'big') + message

# Desempaqueta el cuerpo de un mensaje
# Esta función es necesaria porque:
# 1. Verifica el tamaño mínimo del cuerpo
# 2. Separa el ID del contenido
# 3. Devuelve los componentes en formato utilizable
def unpack_message_body(data: bytes) -> tuple:
    if len(data) < 8:
        raise ValueError("Cuerpo de mensaje demasiado corto")
        
    message_id = int.from_bytes(data[:8], 'big')
    content = data[8:]
    return message_id, content
