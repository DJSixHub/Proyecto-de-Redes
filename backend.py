# backend.py
from util import get_local_ip
from discovery import Discovery
from messaging import Messaging

# Callback al recibir un mensaje de texto
def on_msg(from_id, message):
    print(f"[{from_id}] dice: {message}")

# Callback al recibir un archivo
def on_file(from_id, data):
    print(f"Recibido archivo ({len(data)} bytes).")

if __name__ == '__main__':
    user = input("Tu UserID (max 20 chars): ")
    ip   = get_local_ip()
    print(f"Tu IP local: {ip}")

    disc  = Discovery(user)
    disc.start_listener()
    peers = disc.discover()          # dict {user_id: ip}
    print("Vecinos encontrados:", peers)

    msg   = Messaging(user, on_message=on_msg, on_file=on_file)

    while True:
        entrada = input("Enviar a (UserID o lista separada por comas): ")
        texto   = input("Mensaje: ")
        ids     = [u.strip() for u in entrada.split(',') if u.strip()]
        grupo   = {u: peers[u] for u in ids if u in peers}
        if not grupo:
            print("No hay destinatarios válidos. Revisa los UserIDs.")
            continue
        msg.send_group_message(grupo, texto)
