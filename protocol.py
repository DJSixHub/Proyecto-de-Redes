import struct

# Estructura: 20s user_from, 20s user_to, B op_code, I body_id, Q body_len, 50s padding
HEADER_FMT = '!20s20sB I Q 50s'
HEADER_SIZE = struct.calcsize(HEADER_FMT)

RESPONSE_FMT = '!B20s4s'
RESPONSE_SIZE = struct.calcsize(RESPONSE_FMT)

BROADCAST_UID = b'\xFF' * 20

def pack_header(user_from: str, user_to: str | bytes, op_code: int,
                body_id: int = 0, body_len: int = 0) -> bytes:
    uf = user_from.encode('utf-8')[:20].ljust(20, b'\x00')
    if isinstance(user_to, str):
        ut = user_to.encode('utf-8')[:20].ljust(20, b'\x00')
    elif isinstance(user_to, bytes):
        ut = user_to[:20].ljust(20, b'\x00')
    else:
        raise ValueError("user_to debe ser str o bytes")
    return struct.pack(HEADER_FMT, uf, ut, op_code, body_id, body_len, b'\x00' * 50)

def unpack_header(data: bytes) -> dict:
    uf, ut, op, bid, blen, _ = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
    return {
        'user_from': uf.rstrip(b'\x00').decode('utf-8', errors='ignore'),
        'user_to': ut.rstrip(b'\x00').decode('utf-8', errors='ignore'),
        'op_code': op,
        'body_id': bid,
        'body_len': blen
    }

def pack_response(status: int, responder_id: str) -> bytes:
    rid = responder_id.encode('utf-8')[:20].ljust(20, b'\x00')
    return struct.pack(RESPONSE_FMT, status, rid, b'\x00' * 4)

def unpack_response(data: bytes) -> tuple[int, str]:
    status, rid, _ = struct.unpack(RESPONSE_FMT, data[:RESPONSE_SIZE])
    return status, rid.rstrip(b'\x00').decode('utf-8', errors='ignore')
