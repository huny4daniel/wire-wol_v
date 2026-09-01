"""WireWOL 안드로이드 리모컨이 호출하는 최소 API.

mobile-hub-viewer_v처럼 세션 쿠키 기반 페어링을 쓰지 않는다 — 브라우저가 아니라
안드로이드 앱이 매 요청마다 직접 호출하는 단순 원격 명령이라, 쿠키 발급 절차
없이 고정 토큰을 헤더로 실어 보내는 편이 훨씬 단순하다. 토큰은 트레이 "연결
정보 보기" QR에 담겨 나가고, 앱이 그 QR을 스캔해 저장해둔 뒤 매 요청 헤더에
그대로 실어 보낸다.
"""
import csv
import io
import socket
import subprocess

from flask import Flask, request, jsonify

DEFAULT_SHUTDOWN_DELAY_SECONDS = 10
MAX_SHUTDOWN_DELAY_SECONDS = 24 * 60 * 60

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
_WIRELESS_HINTS = ('Wi-Fi', 'Wireless', 'WLAN', '무선')
_TOKEN_HEADER = 'X-WireWOL-Token'


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def get_primary_mac() -> str:
    """mobile-hub-viewer_v의 app/routes/system.py 구현을 그대로 옮겨 적은 것 —
    getmac의 CSV 열 순서는 로캘과 무관하게 고정이라 이름 대신 순서로 파싱한다."""
    try:
        result = subprocess.run(
            ['getmac', '/fo', 'csv', '/v'],
            capture_output=True, text=True, encoding='cp949', errors='replace',
            creationflags=_NO_WINDOW)
        rows = list(csv.reader(io.StringIO(result.stdout)))
        candidates = [
            (row[0], row[1], row[2], row[3] if len(row) > 3 else '')
            for row in rows[1:]
            if len(row) >= 3 and row[2] and row[2] != 'N/A'
        ]
        active = [c for c in candidates if c[3].startswith('\\Device\\') and 'Bluetooth' not in c[1]]
        pool = active or candidates
        for name, adapter, phys_addr, transport in pool:
            if any(hint in name for hint in _WIRELESS_HINTS):
                return phys_addr
        if pool:
            return pool[0][2]
    except (OSError, subprocess.SubprocessError):
        pass
    return ''


def create_app(config) -> Flask:
    app = Flask(__name__)

    @app.before_request
    def check_token():
        if request.headers.get(_TOKEN_HEADER) != config.token:
            return jsonify(error='invalid token'), 401

    @app.route('/api/ping')
    def ping():
        """앱이 종료 버튼을 누르기 전 PC가 실제로 켜져 응답하는지 확인하는
        용도(WOL은 매직 패킷을 쏘기만 할 뿐 도달 확인이 없어서, 종료 명령을
        섣불리 보내 엉뚱하게 실패하는 것을 막기 위함)."""
        return jsonify(ok=True, mac=get_primary_mac())

    @app.route('/api/shutdown', methods=['POST'])
    def shutdown():
        """delay_seconds를 JSON 바디로 받으면 그만큼 뒤에 종료를 예약한다(즉시
        끄기 버튼은 값을 안 보내 기본 10초 지연을 그대로 쓰고, 예약 종료는 앱이
        사용자가 입력한 분을 초로 환산해 보낸다) — 둘 다 같은 shutdown /t 명령이라
        취소도 항상 /api/shutdown/cancel 하나로 처리된다.

        Windows는 이미 예약된 종료가 있는 채로 shutdown /s /t를 다시 호출하면
        갱신되지 않고 그냥 실패한다 — 즉시 끄기와 예약 끄기가 같은 명령을 쓰다
        보니 둘 중 하나를 걸어둔 채 나머지를 누르면 실패 토스트만 뜨는 문제가
        있었다. 매번 새로 걸기 전에 기존 예약을 먼저 취소해 항상 최신 요청으로
        덮어써지도록 한다 — 예약이 없을 때의 /a 실패는 무시해도 되는 정상 상황."""
        delay = DEFAULT_SHUTDOWN_DELAY_SECONDS
        body = request.get_json(silent=True) or {}
        raw_delay = body.get('delay_seconds')
        if raw_delay is not None:
            try:
                delay = int(raw_delay)
            except (TypeError, ValueError):
                return jsonify(error='delay_seconds 값이 올바르지 않습니다'), 400
            if not (0 <= delay <= MAX_SHUTDOWN_DELAY_SECONDS):
                return jsonify(error='delay_seconds 범위가 올바르지 않습니다'), 400
        subprocess.run(['shutdown', '/a'], creationflags=_NO_WINDOW)
        try:
            subprocess.run(['shutdown', '/s', '/f', '/t', str(delay)],
                            check=True, creationflags=_NO_WINDOW)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return jsonify(error='종료 명령을 실행할 수 없습니다'), 500
        return jsonify(ok=True, delay=delay)

    @app.route('/api/shutdown/cancel', methods=['POST'])
    def cancel_shutdown():
        try:
            subprocess.run(['shutdown', '/a'], check=True, creationflags=_NO_WINDOW)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return jsonify(error='예약된 종료가 없습니다'), 400
        return jsonify(ok=True)

    return app


def run_server(app: Flask, host: str, port: int):
    from werkzeug.serving import make_server
    return make_server(host, port, app, threaded=True)
