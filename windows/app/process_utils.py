"""헤드리스 서버 프로세스(--server)와 트레이 프로세스(--tray)가 서로 다른
프로세스로 나뉘어 있어, 트레이의 "종료" 메뉴가 자신이 직접 갖고 있지 않은
서버 프로세스를 끄려면 PID를 파일로 공유하는 것 외에는 마땅한 방법이 없다
(mobile-hub-viewer_v의 app/process_utils.py와 동일한 이유로 동일한 방식)."""
import os
import subprocess

from .config import BASE_DIR

PID_FILE = os.path.join(BASE_DIR, 'wirewol_server.pid')

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0


def write_server_pid():
    with open(PID_FILE, 'w', encoding='utf-8') as f:
        f.write(str(os.getpid()))


def clear_server_pid():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def read_server_pid():
    try:
        with open(PID_FILE, 'r', encoding='utf-8') as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def is_process_alive(pid: int) -> bool:
    result = subprocess.run(
        ['tasklist', '/FI', f'PID eq {pid}'],
        capture_output=True, text=True, creationflags=_NO_WINDOW)
    return str(pid) in result.stdout


def _run_elevated(exe: str, args) -> bool:
    """일반 권한으로 taskkill이 실패하는 경우(서버가 SYSTEM 계정으로 돌고
    있는 게 보통 이유)에만 쓰는 UAC 승격 재시도."""
    full_arg_line = subprocess.list2cmdline(args)
    ps_literal = "'" + full_arg_line.replace("'", "''") + "'"
    ps_cmd = (
        f'$p = Start-Process -FilePath {exe} -ArgumentList {ps_literal} '
        f'-Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode'
    )
    result = subprocess.run(
        ['powershell', '-NoProfile', '-Command', ps_cmd],
        capture_output=True, creationflags=_NO_WINDOW)
    return result.returncode == 0


def stop_server_process() -> bool:
    """PID 파일에 기록된 헤드리스 서버 프로세스를 강제 종료한다. 이 서버는
    보통 SYSTEM 계정(작업 스케줄러, --server)으로 돌기 때문에 일반 사용자
    권한의 taskkill은 "액세스가 거부되었습니다"로 실패한다 — 그때만 한 번 더
    UAC 승인을 받아 재시도한다."""
    pid = read_server_pid()
    if pid is None or not is_process_alive(pid):
        clear_server_pid()
        return False
    subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, creationflags=_NO_WINDOW)
    if is_process_alive(pid):
        _run_elevated('taskkill', ['/PID', str(pid), '/F'])
    stopped = not is_process_alive(pid)
    if stopped:
        clear_server_pid()
    return stopped
