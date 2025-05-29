# core/protocol.py

import struct

# Este archivo implementa el protocolo LCP (Local Chat Protocol) que define la estructura y formato
# de los mensajes intercambiados en el sistema de chat. El flujo de datos comienza con la definición
# de constantes y tamaños de campos según la especificación, luego proporciona funciones para
# empaquetar y desempaquetar headers, respuestas y cuerpos de mensajes. El protocolo maneja
# la comunicación tanto unicast como broadcast, soporta diferentes tipos de operaciones (echo,
# mensajes y archivos) y garantiza la integridad de los datos mediante validaciones estrictas.

# Configuración de puertos para la comunicación
UDP_PORT = 9990
TCP_PORT = 9990

# Definición de tamaños de campos según la especificación del protocolo
USER_ID_SIZE = 20
OP_CODE_SIZE = 1
BODY_ID_SIZE = 1
BODY_LENGTH_SIZE = 8
HEADER_RESERVED_SIZE = 50
RESPONSE_RESERVED_SIZE = 4

# Cálculo del tamaño total del header (100 bytes) y respuesta (25 bytes)
HEADER_SIZE = USER_ID_SIZE + USER_ID_SIZE + OP_CODE_SIZE + BODY_ID_SIZE + BODY_LENGTH_SIZE + HEADER_RESERVED_SIZE
RESPONSE_SIZE = OP_CODE_SIZE + USER_ID_SIZE + RESPONSE_RESERVED_SIZE

# Identificador especial para mensajes broadcast
BROADCAST_UID = b'\xff' * USER_ID_SIZE

# Formato de empaquetado para respuestas
RESPONSE_FMT = '!B20s4x'  # status(1) + responder(20) + padding(4)

# Códigos de operación soportados por el protocolo
OP_ECHO = 0
OP_MESSAGE = 1
OP_FILE = 2

# Códigos de estado para las respuestas
RESP_OK = 0
RESP_BAD_REQUEST = 1
RESP_INTERNAL_ERROR = 2

# Empaqueta un header LCP de 100 bytes con los campos especificados, validando
# cada campo según las restricciones del protocolo. Es necesario para crear
# paquetes que cumplan con la especificación antes de enviarlos.
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
    
    header[0:USER_ID_SIZE] = user_from.ljust(USER_ID_SIZE, b'\x00')[:USER_ID_SIZE]
    header[USER_ID_SIZE:2*USER_ID_SIZE] = user_to.ljust(USER_ID_SIZE, b'\x00')[:USER_ID_SIZE]
    
    header[40] = op_code
    header[41] = body_id
    
    header[42:50] = body_len.to_bytes(BODY_LENGTH_SIZE, 'big')
    
    return bytes(header)

# Desempaqueta y valida un header LCP, extrayendo todos sus campos en un diccionario.
# Es necesario para procesar los paquetes recibidos y verificar su validez antes
# de procesarlos.
def unpack_header(data: bytes) -> dict:
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

# Empaqueta una respuesta LCP de 25 bytes con el estado y el identificador del
# respondedor. Es necesario para generar respuestas estandarizadas a los
# mensajes recibidos.
def pack_response(status: int, responder: bytes) -> bytes:
    if status not in (RESP_OK, RESP_BAD_REQUEST, RESP_INTERNAL_ERROR):
        raise ValueError(f"status inválido: {status}")
    if not isinstance(responder, bytes):
        raise ValueError("responder debe ser bytes")
        
    resp_id = responder.ljust(USER_ID_SIZE, b'\x00')[:USER_ID_SIZE]
    
    return struct.pack(RESPONSE_FMT, status, resp_id)

# Desempaqueta y valida una respuesta LCP, extrayendo el estado y el identificador
# del respondedor. Es necesario para procesar las respuestas recibidas y
# determinar el resultado de una operación.
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

# Empaqueta el cuerpo de un mensaje con su identificador y contenido.
# Es necesario para preparar el contenido de los mensajes antes de
# enviarlos según el formato especificado.
def pack_message_body(body_id: int, message: bytes) -> bytes:
    if not 0 <= body_id <= 255:
        raise ValueError("body_id debe estar entre 0 y 255")
    
    return body_id.to_bytes(8, 'big') + message

# Desempaqueta el cuerpo de un mensaje, separando el identificador del contenido.
# Es necesario para extraer el contenido de los mensajes recibidos y procesarlos
# adecuadamente.
def unpack_message_body(data: bytes) -> tuple:
    if len(data) < 8:
        raise ValueError("Cuerpo de mensaje demasiado corto")
        
    message_id = int.from_bytes(data[:8], 'big')
    content = data[8:]
    return message_id, content
