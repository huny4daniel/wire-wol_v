"""WireWOL 컴패니언 진입점.

WireWOL 안드로이드 앱(WireGuard + Wake-on-LAN 리모컨)이 PC를 원격 종료할 수
있도록, PC 쪽에서 명령을 받아줄 최소한의 상주 프로그램. PC 켜기(WOL)는 앱이
매직 패킷을 직접 쏘는 것이라 PC 쪽에 아무 프로그램이 없어도 되지만, PC
끄기는 PC가 뭔가 받아서 실행해줘야 하므로 이 프로그램이 필요하다.

mobile-hub-viewer_v의 hub.pyw와 동일하게 인자에 따라 세 가지 모드로 갈라진다.
인자 없이 실행하면(더블클릭) 서버+트레이가 한 프로세스에서 같이 뜬다.
"자동 시작 등록"을 켜면 아래 두 프로세스로 나뉘어 각자 등록된다 — 서버
(`--server`)는 작업 스케줄러가 로그인 여부와 상관없이 부팅 시 SYSTEM 계정으로
띄우고(그래야 아무도 로그인 안 한 PC도 원격 종료 명령을 받을 수 있다), 트레이
(`--tray`)는 로그인 시 시작프로그램으로 뜬다."""
import socket
import sys
import threading

import win32api
import win32event
import winerror

from app.config import WireWolConfig
from app.server import create_app, run_server
from app import process_utils, tray

_COMBINED_MUTEX_NAME = 'WireWOL_SingleInstanceMutex'
_SERVER_MUTEX_NAME = 'WireWOL_ServerMutex'
_TRAY_MUTEX_NAME = 'WireWOL_TrayMutex'


def _acquire_lock(name: str):
    """이미 같은 모드의 인스턴스가 떠 있으면 None을 반환한다 — 없으면 두 번째
    실행이 같은 포트에 바인딩하려다 OSError로 조용히 죽는다(.pyw라 콘솔이
    없어서 아무 설명 없이 "눌러도 반응 없음"으로만 보인다)."""
    mutex = win32event.CreateMutex(None, False, name)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return None
    return mutex


def _port_in_use(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex(('127.0.0.1', port)) == 0
    finally:
        s.close()


def main_combined():
    """인자 없이 실행 — 서버+트레이가 한 프로세스에서 같이 뜬다."""
    mutex = _acquire_lock(_COMBINED_MUTEX_NAME)
    if mutex is None:
        return

    config = WireWolConfig()
    app = create_app(config)
    httpd = run_server(app, '0.0.0.0', config.server_port)

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    tray.run(config, httpd)


def main_server():
    """`--server`: 트레이 없이 서버만 — 작업 스케줄러가 부팅 시 SYSTEM 계정,
    로그인 여부와 상관없이 이 모드로 띄운다."""
    mutex = _acquire_lock(_SERVER_MUTEX_NAME)
    if mutex is None:
        return

    config = WireWolConfig()
    app = create_app(config)
    httpd = run_server(app, '0.0.0.0', config.server_port)
    process_utils.write_server_pid()
    try:
        httpd.serve_forever()
    finally:
        process_utils.clear_server_pid()


def main_tray():
    """`--tray`: 트레이 아이콘만 — 로그인 시 시작프로그램으로 뜬다. 서버는
    별도 `--server` 프로세스가 이미 띄워뒀다고 가정하지만, 아직 자동 시작을
    등록하지 않았거나 방금 부팅 직후라 아직 안 떠 있는 경우를 대비해 포트가
    비어있으면 이 프로세스 안에서 대신 띄운다."""
    mutex = _acquire_lock(_TRAY_MUTEX_NAME)
    if mutex is None:
        return

    config = WireWolConfig()
    embedded_httpd = None
    if not _port_in_use(config.server_port):
        app = create_app(config)
        embedded_httpd = run_server(app, '0.0.0.0', config.server_port)
        threading.Thread(target=embedded_httpd.serve_forever, daemon=True).start()

    tray.run_tray_only(config, embedded_httpd=embedded_httpd)


def main():
    args = sys.argv[1:]
    if '--server' in args:
        main_server()
    elif '--tray' in args:
        main_tray()
    else:
        main_combined()


if __name__ == '__main__':
    main()
