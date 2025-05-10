import threading
import os

from constants import UDP_PORT, TCP_PORT
from neighbor_table import NeighborTable
from discovery import start_autodiscovery
from messaging import Messaging
from file_transfer import FileTransfer


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    self_id = input("Ingrese su UserId (max 20 caracteres): ").strip()[:20]
    table = NeighborTable()

   
    start_autodiscovery(self_id, table)

   
    messaging = Messaging(self_id, table, on_message=on_message)
    filetrans = FileTransfer(self_id, table, receive_dir='received_files')

    
    os.makedirs('received_files', exist_ok=True)

    while True:
        clear_screen()
        print("=== LCP Terminal Interface ===")
        print("Vecinos detectados:")
        for uid, ip in table.get_neighbors().items():
            print(f" - {uid} @ {ip}")
        print("\nOpciones:")
        print("1) Enviar mensaje")
        print("2) Enviar archivo")
        print("3) Refrescar vecinos")
        print("4) Salir")

        choice = input("Seleccione una opción: ").strip()
        if choice == '1':
            text = input("Texto a enviar: ")
            messaging.send_message(text)
            input("Mensaje enviado. Enter para continuar.")
        elif choice == '2':
            path = input("Ruta de archivo a enviar: ").strip()
            if os.path.isfile(path):
                filetrans.send_file(path)
            else:
                print("Archivo no encontrado.")
            input("Enter para continuar.")
        elif choice == '3':
            # ya el autodescubrimiento corre 
            input("Press Enter to refresh.")
        elif choice == '4':
            print("Saliendo...")
            break
        else:
            print("Opción inválida.")
            input("Enter para continuar.")

def on_message(text: str, from_id: str):
    print(f"\n>>> Nuevo mensaje de {from_id}: {text}")
    input("Enter para volver al menú.")

if __name__ == '__main__':
    main()
