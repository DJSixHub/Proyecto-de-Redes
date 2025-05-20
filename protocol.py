# protocol.py
import struct

# Empaqueta y desempaqueta headers y respuestas según LCP
_HEADER_FMT    = '!20s20sB B Q 50s'
HEADER_SIZE    = struct.calcsize(_HEADER_FMT)
_RESPONSE_FMT  = '!B20s4s'
RESPONSE_SIZE  = struct.calcsize(_RESPONSE_FMT)

# Empaqueta la cabecera UDP con IDs, opcode y longitud
def pack_header(user_from: str, user_to: str, op_code: int,
                body_id: int = 0, body_len: int = 0) -> bytes:
    uf = user_from.encode()[:20].ljust(20, b'\x00')
    ut = user_to.encode()[:20].ljust(20, b'\x00')
    return struct.pack(_HEADER_FMT, uf, ut, op_code, body_id, body_len, b'\x00'*50)

# Desempaqueta la cabecera UDP y retorna campos en dict
def unpack_header(data: bytes) -> dict:
    uf, ut, op, bid, blen, _ = struct.unpack(_HEADER_FMT, data[:HEADER_SIZE])
    return {
        'user_from': uf.rstrip(b'\x00').decode(),
        'user_to':   ut.rstrip(b'\x00').decode(),
        'op_code':   op,
        'body_id':   bid,
        'body_len':  blen
    }

# Empaqueta la respuesta con estado y UserID del servidor
def pack_response(status: int, responder_id: str) -> bytes:
    rid = responder_id.encode()[:20].ljust(20, b'\x00')
    return struct.pack(_RESPONSE_FMT, status, rid, b'\x00'*4)

# Desempaqueta la respuesta y retorna tupla (status, responder_id)
def unpack_response(data: bytes) -> tuple[int, str]:
    status, rid, _ = struct.unpack(_RESPONSE_FMT, data[:RESPONSE_SIZE])
    return status, rid.rstrip(b'\x00').decode()
