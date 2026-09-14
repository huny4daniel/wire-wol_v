"""공식 WireGuard for Windows 클라이언트를 CLI로 조작한다.

안드로이드는 GoBackend를 앱 안에 직접 임베딩하지만, 그에 대응하는 손쉬운
Windows 라이브러리가 없다 — 대신 사용자가 이미 설치했을 공식 WireGuard
클라이언트(wireguard.exe)의 터널 서비스 관리 기능을 그대로 빌려 쓴다.

- 켜기: `.conf`를 임시 파일로 써서 `wireguard.exe /installtunnelservice
  <경로>`를 실행한다 — 이 명령 하나로 윈도우 서비스 등록과 기동을 동시에
  한다. `.conf` 파일 이름(확장자 제외)이 곧 터널/서비스 이름이 되므로 매번
  같은 이름(wirewolclient)으로 고정해 이전 실행의 서비스와 충돌하지 않게
  한다.
- 끄기: `/uninstalltunnelservice wirewolclient`로 서비스를 지운다 — 중지와
  제거가 한 번에 된다. 다음에 켤 때 설정이 바뀌었을 수 있으니(설정 화면에서
  새 .conf를 붙여넣었을 수 있음) 매번 새로 설치하는 편이 오래된 서비스가
  남아 꼬이는 것보다 낫다.

터널 서비스를 설치/제거하려면 관리자 권한이 필요하다 — 매번 UAC 승인을
띄우지 않도록 클라이언트 앱 자체를 시작 시 한 번만 관리자 권한으로
재실행해두므로(wirewol_client.pyw 참고), 여기서는 별도 상승 없이 그냥
실행한다.
"""
import os
import subprocess
import tempfile

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
_TUNNEL_NAME = 'wirewolclient'
_DEFAULT_WIREGUARD_EXE = r'C:\Program Files\WireGuard\wireguard.exe'


class WireGuardError(Exception):
    pass


def find_wireguard_exe() -> str | None:
    if os.path.exists(_DEFAULT_WIREGUARD_EXE):
        return _DEFAULT_WIREGUARD_EXE
    return None


def _run(args) -> bool:
    result = subprocess.run(args, capture_output=True, creationflags=_NO_WINDOW)
    return result.returncode == 0


def is_up() -> bool:
    result = subprocess.run(
        ['sc', 'query', f'WireGuardTunnel${_TUNNEL_NAME}'],
        capture_output=True, text=True, creationflags=_NO_WINDOW)
    return 'RUNNING' in result.stdout


def bring_up(conf_text: str):
    wireguard_exe = find_wireguard_exe()
    if not wireguard_exe:
        raise WireGuardError('공식 WireGuard 클라이언트가 설치되어 있지 않습니다 (wireguard.com/install)')
    conf_path = os.path.join(tempfile.gettempdir(), f'{_TUNNEL_NAME}.conf')
    with open(conf_path, 'w', encoding='utf-8') as f:
        f.write(conf_text)
    try:
        if not _run([wireguard_exe, '/installtunnelservice', conf_path]):
            raise WireGuardError('WireGuard 터널을 시작할 수 없습니다')
    finally:
        try:
            os.remove(conf_path)
        except OSError:
            pass


def bring_down():
    wireguard_exe = find_wireguard_exe()
    if not wireguard_exe:
        raise WireGuardError('공식 WireGuard 클라이언트가 설치되어 있지 않습니다 (wireguard.com/install)')
    if not _run([wireguard_exe, '/uninstalltunnelservice', _TUNNEL_NAME]):
        raise WireGuardError('WireGuard 터널을 끌 수 없습니다')
