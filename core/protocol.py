# core/protocol.py

import struct

# Puertos por defecto (pueden parametrizarse si se desea)
UDP_PORT = 9990
TCP_PORT = 9990

# UID de broadcast (20 bytes de 0xFF)
BROADCAST_UID = b'\xff' * 20

# Tamaño fijo de la cabecera según especificación:
# 20 + 20 + 1 + 1 + 8 + 50 = 100 bytes
HEADER_SIZE = 100

# Formato de respuesta (status:1 byte, responder_id:20 bytes, padding:4 bytes)
RESPONSE_FMT = '!B20s4s'
RESPONSE_SIZE = struct.calcsize(RESPONSE_FMT)


def pack_header(user_from: bytes,
                user_to:    bytes = BROADCAST_UID,
                op_code:    int   = 0,
                body_id:    int   = 0,
                body_len:   int   = 0) -> bytes:
    """
    Empaqueta un Echo-Request o Message-Request con cabecera de 100 bytes:
      0–19   user_from   (20 bytes)
     20–39   user_to     (20 bytes)
        40   op_code     (1 byte)
        41   body_id     (1 byte)
     42–49   body_len    (8 bytes, big-endian)
     50–99   padding     (50 bytes de ceros)
    """
    header = bytearray(HEADER_SIZE)
    # From / To
    header[ 0:20] = user_from.ljust(20, b'\x00')[:20]
    header[20:40] = user_to.ljust(20, b'\x00')[:20]
    # Códigos
    header[40] = op_code
    header[41] = body_id
    # Longitud de cuerpo
    header[42:50] = body_len.to_bytes(8, 'big')
    # header[50:100] ya está en cero
    return bytes(header)


def unpack_header(data: bytes) -> dict:
    """
    Desempaqueta una cabecera de HEADER_SIZE bytes:
    devuelve un dict con keys user_from, user_to, op_code, body_id, body_len.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Header demasiado corto: {len(data)} bytes (esperado {HEADER_SIZE})")
    h = data[:HEADER_SIZE]
    return {
        'user_from': h[ 0:20].rstrip(b'\x00'),
        'user_to':   h[20:40].rstrip(b'\x00'),
        'op_code':   h[40],
        'body_id':   h[41],
        'body_len':  int.from_bytes(h[42:50], 'big'),
    }


def pack_response(status: int,
                  responder: bytes) -> bytes:
    """
    Empaqueta una respuesta a un Echo-Request con tamaño RESPONSE_SIZE (25 bytes):
      status      (1 byte)
      responder   (20 bytes)
      padding     (4 bytes)
    """
    # Asegura que responder cabe en 20 bytes
    resp_id = responder.ljust(20, b'\x00')[:20]
    padding = b'\x00' * 4
    return struct.pack(
        RESPONSE_FMT,
        status,
        resp_id,
        padding
    )


def unpack_response(data: bytes) -> dict:
    """
    Desempaqueta una respuesta de RESPONSE_SIZE bytes.
    """
    if len(data) < RESPONSE_SIZE:
        raise ValueError(f"Response demasiado corto: {len(data)} bytes (esperado {RESPONSE_SIZE})")
    status, responder, _ = struct.unpack(
        RESPONSE_FMT,
        data[:RESPONSE_SIZE]
    )
    return {
        'status':    status,
        'responder': responder.rstrip(b'\x00')
    }
