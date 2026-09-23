"""Wake-on-LAN 매직 패킷 전송 — android/.../MainActivity.kt의 sendWakeOnLan을
그대로 옮긴 것. 같은 LAN(또는 브로드캐스트가 도달하는 WireGuard 터널) 안에
있을 때만 유효하다."""
import re
import socket

_MAC_SPLIT_RE = re.compile(r'[:\-]')


def _targets(host: str | None) -> list[str]:
    """255.255.255.255(제한 브로드캐스트)는 라우터를 넘지 못해 WireGuard
    터널로는 집 LAN에 닿지 않는다 — PC 주소 기준 /24 지정 브로드캐스트와
    PC 주소 자체(공유기에 ARP가 남아있는 동안 유효)로도 함께 보낸다."""
    targets = ['255.255.255.255']
    parts = (host or '').split('.')
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        targets.append('.'.join(parts[:3] + ['255']))
        targets.append(host)
    return targets


def send_magic_packet(mac: str, host: str | None = None):
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
        for target in _targets(host):
            try:
                sock.sendto(packet, (target, 9))
            except OSError:
                pass
    finally:
        sock.close()
