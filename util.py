import socket
import psutil

# Este archivo proporciona utilidades para la gestión de redes y configuración de interfaces.
# El flujo principal consiste en analizar todas las interfaces de red disponibles en el sistema,
# filtrar las interfaces virtuales o desconectadas, y obtener la dirección IP local válida junto
# con su dirección de broadcast correspondiente. Este proceso es esencial para establecer la
# comunicación en la red local y permitir el descubrimiento de otros nodos.

# Analiza todas las interfaces de red del sistema para encontrar una IP local válida y su dirección
# de broadcast correspondiente. Excluye interfaces virtuales, desconectadas o irrelevantes como
# VirtualBox, VMware, loopback y Bluetooth. Es necesario para establecer la base de comunicación
# en la red local.
def get_local_ip_and_broadcast():
    for iface, addrs in psutil.net_if_addrs().items():
        stats = psutil.net_if_stats().get(iface)

        if not stats or not stats.isup:
            continue

        excluded = ["virtualbox", "vmware", "loopback", "bluetooth", "ethernet 2", "conexión de red bluetooth"]
        if any(x.lower() in iface.lower() for x in excluded):
            continue

        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                ip = addr.address
                netmask = addr.netmask
                if not ip or not netmask:
                    continue

                ip_parts = list(map(int, ip.split('.')))
                mask_parts = list(map(int, netmask.split('.')))
                broadcast_parts = [(ip_parts[i] | (~mask_parts[i] & 0xff)) for i in range(4)]
                broadcast = '.'.join(map(str, broadcast_parts))

                print(f"🧪 IP usada: {ip}, Broadcast: {broadcast}, Interfaz: {iface}")
                return ip, broadcast

    raise RuntimeError("❌ No se encontró una interfaz de red válida.")
