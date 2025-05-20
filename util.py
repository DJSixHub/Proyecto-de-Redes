import socket
import psutil

def get_local_ip_and_broadcast():
    for iface, addrs in psutil.net_if_addrs().items():
        stats = psutil.net_if_stats().get(iface)
        if not stats or not stats.isup:
            continue  # omitir interfaces desconectadas

        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                ip = addr.address
                netmask = addr.netmask

                ip_parts = list(map(int, ip.split('.')))
                mask_parts = list(map(int, netmask.split('.')))
                broadcast_parts = [(ip_parts[i] | (~mask_parts[i] & 0xff)) for i in range(4)]
                broadcast = '.'.join(map(str, broadcast_parts))
                print(f"🧪 IP usada: {ip}, Broadcast: {broadcast}, Interfaz: {iface}")
                return ip, broadcast

    raise RuntimeError("No se encontró una interfaz de red válida.")
