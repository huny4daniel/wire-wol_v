"""윈도우 로그인 계정에 묶인(DPAPI) 암호화 저장소.

안드로이드 앱은 페어링 정보/원격 WOL 자격 증명/WireGuard 개인 키가 담긴
설정을 EncryptedSharedPreferences(AES256)에 저장한다. 데스크톱에는 그런
표준 API가 없어 대신 Windows DPAPI(CryptProtectData/CryptUnprotectData)를
쓴다 — 같은 윈도우 계정으로 로그인한 사용자만 복호화할 수 있어 목적이
동일하다. pywin32는 이미 windows/ 컴패니언이 의존성으로 쓰고 있다.

세 종류의 설정(pairing, router_wol, wireguard)을 하나의 암호화 파일에
같이 담아둔다 — 안드로이드처럼 굳이 별도 파일로 나눌 이유가 없다(전부
같은 사용자 하나만 접근 가능한 로컬 파일이라 격리 이점이 없다).
"""
import json
import os
import sys

import win32crypt

if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    # app/config.py -> app -> client (wirewol_client.pyw와 같은 위치)
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECRETS_FILE = os.path.join(_BASE_DIR, 'wirewol_client_secrets.dat')

DEFAULT_ROUTER_PORT = '443'


class ClientConfig:
    def __init__(self):
        self._data = {}
        self.load()

    # ---- 저장/불러오기 ----

    def load(self):
        path = os.path.normpath(SECRETS_FILE)
        if not os.path.exists(path):
            self._data = {}
            return
        try:
            with open(path, 'rb') as f:
                encrypted = f.read()
            _, plain = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
            self._data = json.loads(plain.decode('utf-8'))
        except Exception:
            self._data = {}

    def _save(self):
        plain = json.dumps(self._data, ensure_ascii=False).encode('utf-8')
        encrypted = win32crypt.CryptProtectData(plain, 'WireWOL client secrets', None, None, None, 0)
        path = os.path.normpath(SECRETS_FILE)
        with open(path, 'wb') as f:
            f.write(encrypted)

    # ---- 페어링(컴패니언 연결 정보) ----

    def load_pairing(self) -> dict | None:
        pairing = self._data.get('pairing')
        if not pairing or not all(pairing.get(k) for k in ('host', 'port', 'token')):
            return None
        return pairing

    def save_pairing(self, host: str, port: int, token: str, mac: str = ''):
        existing_mac = (self._data.get('pairing') or {}).get('mac', '')
        self._data['pairing'] = {
            'host': host,
            'port': port,
            'token': token,
            'mac': mac or existing_mac,
        }
        self._save()

    def save_mac(self, mac: str):
        pairing = self._data.setdefault('pairing', {})
        pairing['mac'] = mac
        self._save()

    def clear_pairing(self):
        self._data.pop('pairing', None)
        self._save()

    # ---- 원격 WOL(공유기 API) ----

    def load_router_wol(self) -> dict | None:
        router = self._data.get('router_wol')
        if not router or not all(router.get(k) for k in ('host', 'port', 'id', 'password')):
            return None
        return router

    def save_router_wol(self, host: str, port: str, user_id: str, password: str):
        self._data['router_wol'] = {'host': host, 'port': port, 'id': user_id, 'password': password}
        self._save()

    def clear_router_wol(self):
        self._data.pop('router_wol', None)
        self._save()

    def get_pinned_cert_fingerprint(self, host: str) -> str | None:
        return self._data.get('router_cert_fp', {}).get(host)

    def set_pinned_cert_fingerprint(self, host: str, fingerprint: str):
        self._data.setdefault('router_cert_fp', {})[host] = fingerprint
        self._save()

    # ---- WireGuard 설정(.conf 원문) ----

    def load_wireguard_conf(self) -> str | None:
        return self._data.get('wireguard_conf') or None

    def save_wireguard_conf(self, conf_text: str):
        self._data['wireguard_conf'] = conf_text
        self._save()

    def clear_wireguard_conf(self):
        self._data.pop('wireguard_conf', None)
        self._save()

    # ---- 전체 초기화 ----

    def reset_all(self):
        self._data = {}
        self._save()
