import struct
from constants import (
    USERID_SIZE,
    OPCODE_SIZE,
    BODYID_SIZE,
    BODYLEN_SIZE,
    HEADER_SIZE,
    BROADCAST_ID
)


def _fix_length(data: bytes, length: int) -> bytes:
    """Asegura que `data` quede exactamente en `length` bytes (padding o truncado)."""
    if len(data) > length:
        return data[:length]
    return data.ljust(length, b'\x00')

def encode_header(
    user_id_from: str,
    user_id_to: str,
    opcode: int,
    body_id: int = 0,
    body_length: int = 0
) -> bytes:
    
    uid_from = _fix_length(user_id_from.encode('utf-8'), USERID_SIZE)
    uid_to   = BROADCAST_ID if user_id_to == 'broadcast' else _fix_length(user_id_to.encode('utf-8'), USERID_SIZE)

    # Empaquetar OpCode y BodyId
    op     = struct.pack('!B', opcode)
    bid    = struct.pack('!B', body_id)
    blen   = struct.pack('!Q', body_length)  

    # Relleno 
    reserved_len = HEADER_SIZE - (USERID_SIZE*2 + OPCODE_SIZE + BODYID_SIZE + BODYLEN_SIZE)
    reserved = b'\x00' * reserved_len

    return b''.join([uid_from, uid_to, op, bid, blen, reserved])


def decode_header(header: bytes) -> dict:
   
    if len(header) < HEADER_SIZE:
        raise ValueError(f"Header incomplete: expected {HEADER_SIZE} bytes, got {len(header)}")

    
    offset = 0
    uid_from = header[offset:offset+USERID_SIZE].rstrip(b'\x00').decode('utf-8')
    offset += USERID_SIZE

    uid_to   = header[offset:offset+USERID_SIZE].rstrip(b'\x00').decode('utf-8')
    offset += USERID_SIZE

    opcode   = struct.unpack('!B', header[offset:offset+OPCODE_SIZE])[0]
    offset += OPCODE_SIZE

    body_id  = struct.unpack('!B', header[offset:offset+BODYID_SIZE])[0]
    offset += BODYID_SIZE

    body_len = struct.unpack('!Q', header[offset:offset+BODYLEN_SIZE])[0]
   

    return {
        'user_id_from': uid_from,
        'user_id_to': uid_to,
        'opcode': opcode,
        'body_id': body_id,
        'body_length': body_len
    }
