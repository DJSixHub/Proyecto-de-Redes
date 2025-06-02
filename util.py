import socket
import psutil

# Utilidades para configuración de red
# Obtiene IP local y calcula dirección de broadcast correspondiente

# Detecta IP local válida y calcula su broadcast asociado
# Filtra interfaces virtuales/desconectadas y evita localhost
def get_local_ip_and_broadcast():
    for iface, addrs in psutil.net_if_addrs().items():
        stats = psutil.net_if_stats().get(iface)

        if not stats or not stats.isup:
            continue

        # Excluye adaptadores virtuales y no físicos
        excluded = ["virtualbox", "vmware", "loopback", "bluetooth", "ethernet 2", "conexión de red bluetooth"]
        if any(x.lower() in iface.lower() for x in excluded):
            continue

        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                ip = addr.address
                netmask = addr.netmask
                if not ip or not netmask:
                    continue

                # Calcula broadcast: IP OR (NOT netmask)
                ip_parts = list(map(int, ip.split('.')))
                mask_parts = list(map(int, netmask.split('.')))
                broadcast_parts = [(ip_parts[i] | (~mask_parts[i] & 0xff)) for i in range(4)]
                broadcast = '.'.join(map(str, broadcast_parts))

                print(f"🧪 IP usada: {ip}, Broadcast: {broadcast}, Interfaz: {iface}")
                return ip, broadcast

    raise RuntimeError("❌ No se encontró una interfaz de red válida.")
