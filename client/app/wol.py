"""Wake-on-LAN 매직 패킷 전송 — android/.../MainActivity.kt의 sendWakeOnLan을
그대로 옮긴 것. 같은 LAN(또는 브로드캐스트가 도달하는 WireGuard 터널) 안에
있을 때만 유효하다."""
import re
import socket

_MAC_SPLIT_RE = re.compile(r'[:\-]')


def send_magic_packet(mac: str):
    try:
        mac_bytes = bytes(int(part, 16) for part in _MAC_SPLIT_RE.split(mac.strip()) if part)
    except ValueError:
        mac_bytes = b''
    if len(mac_bytes) != 6:
        raise ValueError('MAC 주소 형식이 올바르지 않습니다')
    packet = b'\xff' * 6 + mac_bytes * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, ('255.255.255.255', 9))
    finally:
        sock.close()
