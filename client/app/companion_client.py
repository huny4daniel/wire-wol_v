"""WireWOL 컴패니언(windows/wirewol.pyw)이 여는 최소 API를 호출하는 클라이언트.

android/.../CompanionClient.kt와 동일한 계약이다 — 토큰은 헤더
X-WireWOL-Token으로 실어 보내고, TLS는 쓰지 않는다(LAN이나 WireGuard 터널
안에서만 접근 가능하다고 전제).
"""
from dataclasses import dataclass

import requests

_TOKEN_HEADER = 'X-WireWOL-Token'
_TIMEOUT = 8


@dataclass
class CompanionConfig:
    host: str
    port: int
    token: str

    @property
    def base_url(self) -> str:
        return f'http://{self.host}:{self.port}'


class CompanionError(Exception):
    pass


def _headers(config: CompanionConfig) -> dict:
    return {_TOKEN_HEADER: config.token}


def ping(config: CompanionConfig) -> dict:
    """PC 전원 상태 확인 겸 MAC 조회. 도달 불가/오류 시 CompanionError."""
    try:
        resp = requests.get(f'{config.base_url}/api/ping', headers=_headers(config), timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise CompanionError(str(e)) from e
    if resp.status_code != 200:
        raise CompanionError(_error_message(resp))
    return resp.json()


def shutdown(config: CompanionConfig, delay_seconds: int | None = None) -> dict:
    body = {'delay_seconds': delay_seconds} if delay_seconds is not None else {}
    try:
        resp = requests.post(f'{config.base_url}/api/shutdown', json=body, headers=_headers(config), timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise CompanionError(str(e)) from e
    if resp.status_code != 200:
        raise CompanionError(_error_message(resp))
    return resp.json()


def cancel_shutdown(config: CompanionConfig) -> dict:
    try:
        resp = requests.post(f'{config.base_url}/api/shutdown/cancel', headers=_headers(config), timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise CompanionError(str(e)) from e
    if resp.status_code != 200:
        raise CompanionError(_error_message(resp))
    return resp.json()


def _error_message(resp: requests.Response) -> str:
    try:
        return resp.json().get('error', f'HTTP {resp.status_code}')
    except ValueError:
        return f'HTTP {resp.status_code}'
