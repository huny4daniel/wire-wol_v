"""WireWOL 데스크톱 클라이언트 진입점.

android 리모컨 앱과 동일한 기능(PC 켜기/끄기, 와이어가드 켜기/끄기)을
노트북 등 다른 컴퓨터에서 쓸 수 있게 한다. windows/wirewol.pyw(PC 쪽
상주 프로그램)와는 별개의 프로그램이다 — 이 클라이언트는 명령을 "보내는"
쪽이고, wirewol.pyw는 그 명령을 "받는" 쪽이다.

와이어가드 켜기/끄기는 공식 WireGuard 클라이언트의 터널 서비스
설치/제거(관리자 권한 필요)를 매번 호출한다 — 그때마다 UAC 승인을
띄우는 대신, 앱 시작 시 한 번만 관리자 권한으로 재실행해 이후 호출에서는
추가 승인 없이 동작하게 한다. 빌드된 exe는 PyInstaller `--uac-admin`
매니페스트로 실행 즉시 상승되므로 아래 재실행 로직은 그 경우엔 바로
통과하고, `python wirewol_client.pyw`로 띄우는 개발 환경에서만 실제로
재실행이 일어난다.
"""
import ctypes
import subprocess
import sys

from PyQt5.QtWidgets import QApplication

from app.main_window import MainWindow


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin():
    if getattr(sys, 'frozen', False):
        args = sys.argv[1:]
    else:
        args = [sys.argv[0]] + sys.argv[1:]
    ctypes.windll.shell32.ShellExecuteW(
        None, 'runas', sys.executable, subprocess.list2cmdline(args), None, 1)


def main():
    if not _is_admin():
        _relaunch_as_admin()
        sys.exit(0)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
