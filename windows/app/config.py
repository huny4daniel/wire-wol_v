import os
import sys
import json
import secrets

if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    # app/config.py -> app -> 프로젝트 루트 (wirewol.pyw와 같은 위치)
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = _BASE_DIR

CONFIG_FILE = os.path.join(_BASE_DIR, 'wirewol_config.json')

DEFAULT_PORT = 8677


class WireWolConfig:
    def __init__(self):
        self.token = ''
        self.server_port = DEFAULT_PORT
        # SYSTEM 계정 부팅 작업(--server) 등록 여부 — schtasks 조회 자체가
        # 관리자 권한을 요구해 매번 다시 물어볼 수 없으므로 여기 직접 기록해둔다
        # (mobile-hub-viewer_v의 HubConfig.boot_task_registered와 동일한 이유).
        self.boot_task_registered = False
        self.load()
        if not self.token:
            self.token = secrets.token_urlsafe(24)
            self.save()

    def load(self):
        path = os.path.normpath(CONFIG_FILE)
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            token = data.get('token')
            if isinstance(token, str) and token:
                self.token = token
            port = data.get('server_port')
            if isinstance(port, int) and 0 < port < 65536:
                self.server_port = port
            self.boot_task_registered = bool(data.get('boot_task_registered', False))
        except Exception:
            pass

    def save(self):
        path = os.path.normpath(CONFIG_FILE)
        data = {
            'token': self.token,
            'server_port': self.server_port,
            'boot_task_registered': self.boot_task_registered,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
