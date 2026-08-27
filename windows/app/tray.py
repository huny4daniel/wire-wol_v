"""트레이 아이콘 + 페어링 QR 팝업 + 자동 시작 등록.

mobile-hub-viewer_v의 app/tray.py와 동일한 구조(부팅 시 SYSTEM 계정으로 서버,
로그인 시 트레이)를 그대로 따르되, video/comic 폴더 지정 같은 이 프로젝트에
없는 메뉴는 뺐다."""
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox

import pystray
import qrcode
from PIL import Image, ImageTk

from .server import get_lan_ip, get_primary_mac
from . import process_utils

if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    # app/tray.py -> app -> 프로젝트 루트 (wirewol.pyw와 같은 위치)
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ICON_PATH = os.path.join(_BASE_DIR, 'assets', 'tray_icon.ico') if not getattr(sys, 'frozen', False) \
    else os.path.join(sys._MEIPASS, 'tray_icon.ico')

_STARTUP_SHORTCUT_NAME = 'WireWOL.lnk'
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
_BOOT_TASK_NAME = 'WireWOL_ServerAutoStart'
_LAUNCHER_NAME = 'wirewol_launcher.vbs'


def _wscript_path() -> str:
    return os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'System32', 'wscript.exe')


def _write_launcher(base_dir: str) -> str:
    """exe를 버전이 포함된 파일명(`WireWOL_vX.Y.Z.exe`)으로 새로 받을 때마다
    자동 시작 등록을 다시 하지 않아도 되도록, 등록 자체는 이 고정 경로의
    런처(VBScript)를 가리키게 하고, 런처가 실행될 때마다 같은 폴더에서 가장
    최근에 수정된 WireWOL_v*.exe를 찾아 대신 실행한다(인자는 그대로
    전달). mobile-hub-viewer_v의 app/tray.py._write_launcher와 동일한 방식
    — VBScript를 쓴 건 배치 파일과 달리 콘솔 창 깜빡임 없이 완전히
    숨겨서(WScript.Shell.Run의 windowStyle=0) 실행할 수 있어서다."""
    path = os.path.join(base_dir, _LAUNCHER_NAME)
    content = (
        'Option Explicit\r\n'
        'Dim fso, shell, folder, f, newestFile, newestTime, foundAny, cmdLine, i, args\r\n'
        'Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
        'Set shell = CreateObject("WScript.Shell")\r\n'
        'Set folder = fso.GetFolder(fso.GetParentFolderName(WScript.ScriptFullName))\r\n'
        'foundAny = False\r\n'
        'For Each f In folder.Files\r\n'
        '    If LCase(Left(f.Name, 8)) = "wirewol_" And LCase(Right(f.Name, 4)) = ".exe" Then\r\n'
        '        If (Not foundAny) Or f.DateLastModified > newestTime Then\r\n'
        '            newestTime = f.DateLastModified\r\n'
        '            Set newestFile = f\r\n'
        '            foundAny = True\r\n'
        '        End If\r\n'
        '    End If\r\n'
        'Next\r\n'
        'If foundAny Then\r\n'
        '    args = ""\r\n'
        '    For i = 0 To WScript.Arguments.Count - 1\r\n'
        '        args = args & " " & WScript.Arguments(i)\r\n'
        '    Next\r\n'
        '    cmdLine = """" & newestFile.Path & """" & args\r\n'
        '    shell.Run cmdLine, 0, False\r\n'
        'End If\r\n'
    )
    with open(path, 'w', encoding='utf-8') as fp:
        fp.write(content)
    return path


def _startup_dir() -> str:
    return os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')


def _shortcut_path() -> str:
    return os.path.join(_startup_dir(), _STARTUP_SHORTCUT_NAME)


def _pythonw_and_entry():
    pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    entry = os.path.abspath(sys.argv[0])
    return pythonw, entry


def register_startup():
    """로그인 시 트레이 아이콘만 뜨도록 등록한다(`--tray`) — 서버 자체는
    `register_boot_task()`가 등록하는 부팅 시 작업이 따로 담당한다."""
    import win32com.client
    shell = win32com.client.Dispatch('WScript.Shell')
    shortcut = shell.CreateShortcut(_shortcut_path())
    if getattr(sys, 'frozen', False):
        launcher = _write_launcher(os.path.dirname(sys.executable))
        shortcut.TargetPath = _wscript_path()
        shortcut.Arguments = f'"{launcher}" --tray'
        shortcut.WorkingDirectory = os.path.dirname(sys.executable)
        shortcut.IconLocation = sys.executable
    else:
        pythonw, entry = _pythonw_and_entry()
        shortcut.TargetPath = pythonw
        shortcut.Arguments = f'"{entry}" --tray'
        shortcut.WorkingDirectory = os.path.dirname(entry)
    shortcut.save()


def unregister_startup():
    path = _shortcut_path()
    if os.path.exists(path):
        os.remove(path)


def _server_launch_command() -> str:
    if getattr(sys, 'frozen', False):
        launcher = _write_launcher(os.path.dirname(sys.executable))
        return f'"{_wscript_path()}" "{launcher}" --server'
    pythonw, entry = _pythonw_and_entry()
    return f'"{pythonw}" "{entry}" --server'


def _run_elevated_schtasks(args) -> bool:
    """SYSTEM 계정으로 작업을 만들거나 지우려면 schtasks 자체가 관리자 권한으로
    실행돼야 한다 — PowerShell의 Start-Process -Verb RunAs로 그 순간만 UAC
    승인을 받아 상승시킨다(트레이 앱 전체를 관리자 권한으로 띄우지 않기 위함)."""
    full_arg_line = subprocess.list2cmdline(args)
    ps_literal = "'" + full_arg_line.replace("'", "''") + "'"
    ps_cmd = (
        f'$p = Start-Process -FilePath schtasks -ArgumentList {ps_literal} '
        f'-Verb RunAs -WindowStyle Hidden -Wait -PassThru; exit $p.ExitCode'
    )
    result = subprocess.run(
        ['powershell', '-NoProfile', '-Command', ps_cmd],
        capture_output=True, creationflags=_NO_WINDOW)
    return result.returncode == 0


def register_boot_task() -> bool:
    """로그인 여부와 상관없이 컴퓨터가 켜지면(SYSTEM 계정, ONSTART) 헤드리스
    서버(`--server`)를 바로 띄우는 작업 스케줄러 항목을 만든다 — 이게 있어야
    아무도 로그인하지 않은 상태에서도 폰으로 원격 종료 명령을 보낼 수 있다."""
    args = [
        '/Create', '/TN', _BOOT_TASK_NAME,
        '/TR', _server_launch_command(),
        '/SC', 'ONSTART',
        '/RU', 'SYSTEM',
        '/RL', 'HIGHEST',
        '/F',
    ]
    return _run_elevated_schtasks(args)


def unregister_boot_task() -> bool:
    """등록 여부를 미리 조회하지 않고 그냥 삭제를 시도한다 — SYSTEM 계정
    작업은 조회조차 관리자 권한 없인 "Access is denied"만 돌아와서, 그걸
    "등록 안 됨"으로 잘못 해석하면 실제 등록된 작업의 삭제를 건너뛰게 된다."""
    return _run_elevated_schtasks(['/Delete', '/TN', _BOOT_TASK_NAME, '/F'])


def _pairing_payload(config) -> str:
    return json.dumps({
        'host': get_lan_ip(),
        'port': config.server_port,
        'token': config.token,
        'mac': get_primary_mac(),
    }, ensure_ascii=False)


def _show_pairing_window(config):
    payload = _pairing_payload(config)
    qr_img = qrcode.make(payload).resize((280, 280))

    root = tk.Tk()
    root.title('WireWOL - 연결 정보')
    root.resizable(False, False)

    photo = ImageTk.PhotoImage(qr_img, master=root)
    tk.Label(root, image=photo).pack(padx=16, pady=(16, 8))

    tk.Label(root, text='WireWOL 앱에서 "연결 정보 스캔"으로 찍으세요', fg='#555').pack()
    tk.Label(root, text='(같은 와이파이가 아니어도 되며, 이 QR에는 PC의 MAC/토큰이 포함되어 있으니 주의하세요)',
             fg='#888', wraplength=280, justify='center').pack(padx=16, pady=(4, 16))

    tk.Button(root, text='닫기', command=root.destroy).pack(pady=(0, 16))

    root.mainloop()


def _notify_or_alert(icon, title, message):
    try:
        icon.notify(message, title)
    except Exception:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(title, message)
        root.destroy()


def _run(config, status_label, on_quit):
    image = Image.open(ICON_PATH)

    def on_pairing(icon, item):
        threading.Thread(target=_show_pairing_window, args=(config,), daemon=True).start()

    def on_toggle_autostart(icon, item):
        if config.boot_task_registered:
            unregister_startup()
            unregister_boot_task()
            config.boot_task_registered = False
            config.save()
            icon.notify('자동 시작이 해제되었습니다.', 'WireWOL')
        else:
            register_startup()
            ok = register_boot_task()
            config.boot_task_registered = ok
            config.save()
            if ok:
                icon.notify('다음 부팅부터는 로그인 없이도 원격 종료 명령을 받을 수 있습니다.', '자동 시작 등록 완료')
            else:
                icon.notify('로그인 시 트레이 실행만 등록되었습니다(부팅 시 자동 서버 시작은 관리자 권한 승인이 필요).',
                             '일부만 등록됨')
        icon.update_menu()

    def autostart_text(item):
        return '자동 시작 등록됨 (클릭해서 해제)' if config.boot_task_registered \
            else '자동 시작 등록 (재부팅 후 로그인 없이 원격 종료 가능)'

    menu = pystray.Menu(
        pystray.MenuItem(status_label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('연결 정보 보기', on_pairing),
        pystray.MenuItem(autostart_text, on_toggle_autostart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('종료', on_quit),
    )
    icon = pystray.Icon('wirewol', image, 'WireWOL', menu)
    icon.run()


def run(config, httpd):
    """서버와 트레이가 한 프로세스에서 같이 도는 기본 동작(더블클릭 실행)."""
    def on_quit(icon, item):
        httpd.shutdown()
        icon.stop()

    _run(config, 'WireWOL 실행 중', on_quit)


def run_tray_only(config, embedded_httpd=None):
    """`--tray` 모드: 서버는 별도 프로세스(`--server`, 보통 작업 스케줄러가
    부팅 시 띄운 것)에서 돈다고 가정하고 트레이 UI만 담당한다."""
    def on_quit(icon, item):
        if embedded_httpd is not None:
            embedded_httpd.shutdown()
        else:
            process_utils.stop_server_process()
        icon.stop()

    label = 'WireWOL (트레이)' if embedded_httpd is None else 'WireWOL 실행 중 (임시 내장 서버)'
    _run(config, label, on_quit)
