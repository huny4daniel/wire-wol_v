"""WireWOL 데스크톱 리모컨 메인 창 — android/.../MainActivity.kt의 버튼
구성(PC 켜기/PC 끄기/예약 끄기/와이어가드 켜기/와이어가드 끄기)과 상태
카드를 그대로 옮긴 것.

와이어가드는 토글 버튼 하나가 아니라 켜기/끄기 버튼을 따로 둔다 — 안드로이드
쪽과 동일하게 사용자가 누른 상태를 그대로 유지하며(창을 최소화하거나
백그라운드로 보내도 자동으로 끄지 않음), 데스크톱 리모컨의 다른 버튼들과
같은 조작 방식을 유지하기 위함이다.
"""
import socket
import threading
import time
from datetime import datetime

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from app import companion_client, wireguard_client, wol
from app.companion_client import CompanionConfig, CompanionError
from app.config import ClientConfig
from app.router_wol import RouterWolError, trigger_remote_wake
from app.settings_dialog import SettingsDialog
from app.wireguard_client import WireGuardError

# PC 켜기 폴링: 처음 FAST_POWER_ON_POLL_DURATION_MS 동안은 1초 간격으로
# 빠르게 확인하고(절전 모드에서 깨는 경우처럼 금방 켜질 수도 있어서), 그
# 이후에는(완전 종료 상태에서 부팅하는 경우) 5초 간격으로 늦춘다 — android
# MainActivity.kt의 동일한 폴링 로직과 대응.
_POWER_ON_POLL_INTERVAL_MS = 5_000
_FAST_POWER_ON_POLL_INTERVAL_MS = 1_000
_FAST_POWER_ON_POLL_DURATION_MS = 15_000
_QUICK_SHUTDOWN_SECONDS = 10

# 종료 요청이 실패했을 때(절전 상태일 수 있음) 매직 패킷으로 깨운 뒤
# 컴패니언이 응답할 때까지 재시도하는 간격/최대 대기 시간 — android
# MainActivity.kt의 WAKE_RETRY_POLL_INTERVAL_MS/WAKE_RETRY_TIMEOUT_MS와 대응.
_WAKE_RETRY_POLL_INTERVAL_MS = 1_000
_WAKE_RETRY_TIMEOUT_MS = 30_000

# 창이 떠 있는 동안 PC 전원 상태를 5초마다 자동으로 재확인한다 — android
# MainActivity.kt의 startAutoRefresh(onResume/onPause에 걸림)와 동일한
# 동작으로, 버튼을 누르지 않아도 상태 표시가 계속 최신으로 유지된다.
_AUTO_REFRESH_INTERVAL_MS = 5_000
_CONNECTIVITY_PROBE_TIMEOUT_SECONDS = 1.5


def _is_reachable_directly(host: str, port: int) -> bool:
    """WireGuard 없이 컴패니언 포트로 짧게 직접 연결을 찔러본다 — 지금 집
    안(또는 이미 도달 가능한 상태)인지 판단하는 용도. Wi-Fi 이름(SSID) 비교
    대신 이 방식을 쓰는 이유는 별도 권한이 필요 없고, "실제로 닿는가"만
    보므로 더 정확하기 때문이다(android 앱의 NetworkProbe와 동일한 방식)."""
    try:
        with socket.create_connection((host, port), timeout=_CONNECTIVITY_PROBE_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


class _AsyncBridge(QObject):
    done = pyqtSignal(object, object)  # (result, error)


def run_async(fn, callback):
    """스레드에서 fn()을 실행하고, 끝나면 메인(GUI) 스레드에서 callback(result,
    error)을 호출한다 — 컴패니언/공유기 HTTP 호출이 창을 멈추지 않게 한다."""
    bridge = _AsyncBridge()
    bridge.done.connect(callback)

    def worker():
        try:
            result = fn()
            bridge.done.emit(result, None)
        except Exception as e:  # noqa: BLE001 - 원인 불문 UI에 그대로 보여줌
            bridge.done.emit(None, e)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return bridge  # 참조를 유지해야 emit 전에 GC되지 않는다


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.config = ClientConfig()
        self._bridges = []  # run_async가 만드는 브리지들이 GC되지 않게 붙잡아둔다
        self._power_poll_timer = QTimer(self)
        self._power_poll_timer.setSingleShot(True)
        self._power_poll_timer.timeout.connect(self._poll_power_status)
        self._power_poll_started_at = None
        self._wake_retry_timer = None  # 참조를 유지해야 timeout 전에 GC되지 않는다

        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh_tick)
        self._auto_refresh_timer.start(_AUTO_REFRESH_INTERVAL_MS)

        # 앱을 켜고 전원 상태를 실제로 한 번이라도 확인했는지 — 최초 확인
        # 때만 "확인 중..."을 잠깐 보여주고, 그 이후(자동 재확인/PC 켜기
        # 폴링 등 반복 확인)에는 결과가 올 때까지 직전 상태를 그대로 유지한
        # 채 조용히 백그라운드에서 확인하다가 값이 나오면 그때 갱신한다.
        self._has_checked_power_once = False

        # 예약된 종료가 실제로 실행되는 시점에 와이어가드를 끄기 위한 지연
        # 타이머 — 종료가 취소되면 _cancel_pending_shutdown에서 멈춘다.
        self._wireguard_auto_off_timer = None

        self.setWindowTitle('WireWOL')
        self.setFixedWidth(360)

        layout = QVBoxLayout(self)

        status_box = QVBoxLayout()
        self.status_power_label = QLabel()
        self.status_host_label = QLabel()
        self.status_mac_label = QLabel()
        self.status_wireguard_label = QLabel()
        self.status_shutdown_label = QLabel()
        self.status_shutdown_label.hide()
        for label in (self.status_power_label, self.status_host_label, self.status_mac_label,
                      self.status_wireguard_label, self.status_shutdown_label):
            status_box.addWidget(label)
        layout.addLayout(status_box)

        power_on_button = QPushButton('PC 켜기')
        power_on_button.clicked.connect(self._on_power_on_clicked)
        power_off_button = QPushButton('PC 끄기')
        power_off_button.clicked.connect(self._on_power_off_clicked)
        schedule_button = QPushButton('예약 끄기')
        schedule_button.clicked.connect(self._on_schedule_shutdown_clicked)
        layout.addWidget(power_on_button)
        layout.addWidget(power_off_button)
        layout.addWidget(schedule_button)

        wg_row = QHBoxLayout()
        wg_on_button = QPushButton('와이어가드 켜기')
        wg_on_button.clicked.connect(self._on_wireguard_on_clicked)
        wg_off_button = QPushButton('와이어가드 끄기')
        wg_off_button.clicked.connect(self._on_wireguard_off_clicked)
        wg_row.addWidget(wg_on_button)
        wg_row.addWidget(wg_off_button)
        layout.addLayout(wg_row)

        settings_button = QPushButton('설정')
        settings_button.clicked.connect(self._on_settings_clicked)
        layout.addWidget(settings_button)

        self._refresh_status()
        self._update_pending_shutdown_status()

    # ---- 상태 표시 ----

    def _refresh_status(self):
        pairing = self.config.load_pairing()
        self.status_host_label.setText(
            f'대상: {pairing["host"]}:{pairing["port"]}' if pairing else '대상: 연결 정보 없음')
        mac = (pairing or {}).get('mac', '')
        self.status_mac_label.setText(f'MAC: {mac}' if mac else 'MAC: 없음')
        self._refresh_wireguard_status()
        self._check_power_status(pairing)

    def _auto_refresh_tick(self):
        # PC 켜기 폴링이 이미 돌고 있으면 같은 요청이 중복되니 건너뛴다.
        if not self._power_poll_timer.isActive():
            self._check_power_status(self.config.load_pairing())

    def _refresh_wireguard_status(self):
        if not self.config.load_wireguard_conf():
            self.status_wireguard_label.setText('와이어가드: 설정 안 됨')
            return
        try:
            up = wireguard_client.is_up()
        except Exception:
            up = False
        self.status_wireguard_label.setText('와이어가드: 켜짐' if up else '와이어가드: 꺼짐')

    def _check_power_status(self, pairing, on_result=None):
        if not pairing:
            self.status_power_label.setText('전원: 확인 불가(연결 정보 없음)')
            if on_result:
                on_result(False)
            return
        if not self._has_checked_power_once:
            self.status_power_label.setText('전원: 확인 중...')
        config = CompanionConfig(pairing['host'], pairing['port'], pairing['token'])

        def on_done(result, error):
            self._has_checked_power_once = True
            if error is None:
                self.status_power_label.setText('전원: 켜짐')
                if on_result:
                    on_result(True)
            else:
                self.status_power_label.setText('전원: 꺼짐/확인 불가')
                if on_result:
                    on_result(False)

        self._bridges.append(run_async(lambda: companion_client.ping(config), on_done))

    # ---- 연결 확보(WireGuard 자동 켜기) ----

    def _ensure_connectivity(self, pairing, on_ready):
        """WireGuard가 없거나 이미 켜져 있으면 곧바로 on_ready를 실행한다.
        그 외의 경우엔 WireGuard 없이 컴패니언 포트로 짧게(1.5초) 직접 연결을
        찔러봐서 지금 도달 가능한지(=내부) 확인하고, 안 되면(=외부) 와이어
        가드를 자동으로 켠 뒤 on_ready를 실행한다. PC 켜기/끄기처럼 컴패니언과
        통신이 필요한 동작 앞에 이 함수를 거치면, 매번 손으로 와이어가드부터
        켜야 하는 수고를 없앨 수 있다."""
        conf = self.config.load_wireguard_conf()
        if not conf or wireguard_client.is_up():
            on_ready()
            return

        def on_probe_done(reachable, error):
            if error is None and reachable:
                on_ready()
                return

            def on_bring_up_done(result, error2):
                if error2 is not None:
                    message = str(error2) if isinstance(error2, WireGuardError) else f'WireGuard 자동 연결 실패: {error2}'
                    QMessageBox.warning(self, 'WireGuard', message)
                self._refresh_wireguard_status()
                on_ready()

            self._bridges.append(run_async(lambda: wireguard_client.bring_up(conf), on_bring_up_done))

        self._bridges.append(run_async(lambda: _is_reachable_directly(pairing['host'], pairing['port']), on_probe_done))

    # ---- PC 켜기 ----

    def _on_power_on_clicked(self):
        pairing = self.config.load_pairing()
        mac = (pairing or {}).get('mac', '')
        if not mac:
            QMessageBox.warning(self, '오류', 'MAC 주소가 없어 PC를 깨울 수 없습니다. 설정에서 연결 정보를 다시 확인하세요')
            return

        def proceed():
            try:
                wol.send_magic_packet(mac)
            except ValueError as e:
                QMessageBox.warning(self, '오류', str(e))
                return
            self._trigger_remote_wake_if_configured(mac)
            QMessageBox.information(self, 'PC 켜기', '깨우기 신호를 보냈습니다')
            self._start_power_on_polling(pairing)

        self._ensure_connectivity(pairing, proceed)

    def _trigger_remote_wake_if_configured(self, mac: str):
        router = self.config.load_router_wol()
        if not router:
            return

        def on_done(result, error):
            if error is not None:
                message = str(error) if isinstance(error, RouterWolError) else f'공유기 원격 WOL 실패: {error}'
                QMessageBox.warning(self, '원격 WOL', message)

        self._bridges.append(run_async(lambda: trigger_remote_wake(self.config, router, mac), on_done))

    def _start_power_on_polling(self, pairing):
        self._power_poll_timer.stop()
        if not pairing:
            return
        self._power_poll_started_at = time.monotonic()
        self._power_poll_timer.start(_FAST_POWER_ON_POLL_INTERVAL_MS)

    def _poll_power_status(self):
        pairing = self.config.load_pairing()

        def on_result(is_on):
            if is_on:
                return
            elapsed_ms = (time.monotonic() - self._power_poll_started_at) * 1000
            next_interval = (_FAST_POWER_ON_POLL_INTERVAL_MS
                              if elapsed_ms < _FAST_POWER_ON_POLL_DURATION_MS
                              else _POWER_ON_POLL_INTERVAL_MS)
            self._power_poll_timer.start(next_interval)

        self._check_power_status(pairing, on_result)

    # ---- PC 끄기 ----

    def _on_power_off_clicked(self):
        pairing = self.config.load_pairing()
        if not pairing:
            QMessageBox.warning(self, '오류', '연결 정보가 없습니다')
            return
        if QMessageBox.question(self, 'PC 끄기', '정말 PC를 끌까요?') != QMessageBox.Yes:
            return
        self._request_shutdown(pairing, None)

    def _on_schedule_shutdown_clicked(self):
        pairing = self.config.load_pairing()
        if not pairing:
            QMessageBox.warning(self, '오류', '연결 정보가 없습니다')
            return

        dialog = QDialog(self)
        dialog.setWindowTitle('예약 끄기')
        layout = QHBoxLayout(dialog)
        hour_spin = QSpinBox()
        hour_spin.setRange(0, 23)
        minute_spin = QSpinBox()
        minute_spin.setRange(0, 59)
        minute_spin.setValue(30)
        layout.addWidget(QLabel('시간 후'))
        layout.addWidget(hour_spin)
        layout.addWidget(QLabel('시'))
        layout.addWidget(minute_spin)
        layout.addWidget(QLabel('분'))
        confirm_button = QPushButton('예약')
        confirm_button.clicked.connect(dialog.accept)
        layout.addWidget(confirm_button)

        if dialog.exec_() != QDialog.Accepted:
            return
        delay_seconds = hour_spin.value() * 3600 + minute_spin.value() * 60
        if delay_seconds <= 0:
            QMessageBox.warning(self, '오류', '예약 시간을 입력하세요')
            return
        self._request_shutdown(pairing, delay_seconds)

    def _request_shutdown(self, pairing, delay_seconds):
        def proceed():
            self._attempt_shutdown(pairing, delay_seconds, allow_wake_retry=True)

        self._ensure_connectivity(pairing, proceed)

    def _attempt_shutdown(self, pairing, delay_seconds, allow_wake_retry):
        """컴패니언이 응답하지 않으면(PC가 절전 상태라 서버 프로세스 자체가
        멈춰있는 경우일 수 있음) 매직 패킷으로 깨운 뒤 딱 한 번만 더
        재시도한다 — 절전이 아니라 진짜 꺼져있거나 페어링이 잘못된 경우엔
        매직 패킷을 보내도 응답이 오지 않으니 _wake_then_retry_shutdown의
        타임아웃에서 그대로 실패로 끝난다."""
        config = CompanionConfig(pairing['host'], pairing['port'], pairing['token'])

        def on_done(result, error):
            if error is not None:
                mac = pairing.get('mac', '')
                if allow_wake_retry and mac:
                    self._wake_then_retry_shutdown(pairing, mac, delay_seconds)
                else:
                    message = str(error) if isinstance(error, CompanionError) else f'종료 요청 실패: {error}'
                    QMessageBox.warning(self, '오류', message)
                return
            self._on_shutdown_scheduled(delay_seconds or _QUICK_SHUTDOWN_SECONDS)

        self._bridges.append(run_async(lambda: companion_client.shutdown(config, delay_seconds), on_done))

    def _wake_then_retry_shutdown(self, pairing, mac, delay_seconds):
        """PC가 절전 상태일 때는 매직 패킷을 하드웨어(랜카드)가 직접 받아
        깨우는 것만 가능하고, 컴패니언 서버는 OS가 완전히 깨어난 뒤에야 다시
        요청에 응답할 수 있다 — 그래서 깨운 뒤 서버가 살아날 때까지 짧은
        간격으로 ping을 재시도하다가, 응답이 오는 즉시 종료 요청을 다시
        보낸다."""
        try:
            wol.send_magic_packet(mac)
        except ValueError:
            pass
        self._trigger_remote_wake_if_configured(mac)

        config = CompanionConfig(pairing['host'], pairing['port'], pairing['token'])
        started_at = time.monotonic()

        timer = QTimer(self)
        timer.setSingleShot(True)

        def poll():
            def on_result(is_on):
                if is_on:
                    timer.stop()
                    self._attempt_shutdown(pairing, delay_seconds, allow_wake_retry=False)
                    return
                elapsed_ms = (time.monotonic() - started_at) * 1000
                if elapsed_ms < _WAKE_RETRY_TIMEOUT_MS:
                    timer.start(_WAKE_RETRY_POLL_INTERVAL_MS)
                else:
                    self._wake_retry_timer = None
                    QMessageBox.warning(self, '오류', 'PC가 응답하지 않아 종료할 수 없습니다'
                                         '(절전 상태에서 깨우기에 실패했을 수 있습니다)')

            self._check_power_status(pairing, on_result)

        timer.timeout.connect(poll)
        self._wake_retry_timer = timer
        timer.start(_WAKE_RETRY_POLL_INTERVAL_MS)

    def _schedule_wireguard_auto_off(self, delay_seconds):
        """PC가 실제로 꺼지는 시점에 맞춰(예약 지연이 끝난 뒤) 와이어가드도
        함께 끈다 — 종료 취소 시 그사이엔 여전히 PC에 붙어있어야 하므로,
        예약을 걸 때 곧바로 끄지 않고 지연 시간만큼 기다렸다가 끈다."""
        if self._wireguard_auto_off_timer is not None:
            self._wireguard_auto_off_timer.stop()
            self._wireguard_auto_off_timer = None
        if not self.config.load_wireguard_conf() or not wireguard_client.is_up():
            return

        def on_timeout():
            self._wireguard_auto_off_timer = None

            def on_done(result, error):
                self._refresh_wireguard_status()

            self._bridges.append(run_async(wireguard_client.bring_down, on_done))

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(on_timeout)
        timer.start(delay_seconds * 1000)
        self._wireguard_auto_off_timer = timer

    def _on_shutdown_scheduled(self, delay_seconds):
        self.config.save_pending_shutdown_at(time.time() + delay_seconds)
        self._update_pending_shutdown_status()
        self._schedule_wireguard_auto_off(delay_seconds)
        if delay_seconds <= _QUICK_SHUTDOWN_SECONDS:
            reply = QMessageBox(self)
            reply.setWindowTitle('PC 끄기')
            reply.setText(f'{delay_seconds}초 후 종료됩니다')
            cancel_button = reply.addButton('취소', QMessageBox.ActionRole)
            reply.addButton(QMessageBox.Ok)
            reply.exec_()
            if reply.clickedButton() == cancel_button:
                self._cancel_pending_shutdown()
                return
        else:
            minutes = delay_seconds // 60
            QMessageBox.information(self, 'PC 끄기', f'{minutes}분 후 종료가 예약되었습니다')

    # 예약된 종료가 남아있으면(창을 닫았다가 다시 열어도) 상태 카드에 시각과
    # 함께 보여준다 — android의 updatePendingShutdownStatus와 동일하게,
    # 이미 지난 시각이면 조용히 정리한다.
    def _update_pending_shutdown_status(self):
        target = self.config.load_pending_shutdown_at()
        if not target or target <= time.time():
            self.status_shutdown_label.hide()
            if target:
                self.config.clear_pending_shutdown_at()
            return
        time_label = datetime.fromtimestamp(target).strftime('%H:%M')
        self.status_shutdown_label.setText(f'{time_label}에 종료 예약됨 (클릭하여 취소)')
        self.status_shutdown_label.show()
        try:
            self.status_shutdown_label.mousePressEvent = lambda event: self._cancel_pending_shutdown()
        except Exception:
            pass

    def _cancel_pending_shutdown(self):
        pairing = self.config.load_pairing()
        if not pairing:
            QMessageBox.warning(self, '오류', '연결 정보가 없습니다')
            return
        config = CompanionConfig(pairing['host'], pairing['port'], pairing['token'])

        def on_done(result, error):
            if error is not None:
                message = str(error) if isinstance(error, CompanionError) else f'취소 실패: {error}'
                QMessageBox.warning(self, '오류', message)
                return
            if self._wireguard_auto_off_timer is not None:
                self._wireguard_auto_off_timer.stop()
                self._wireguard_auto_off_timer = None
            self.config.clear_pending_shutdown_at()
            self._update_pending_shutdown_status()
            QMessageBox.information(self, 'PC 끄기', '예약된 종료를 취소했습니다')

        self._bridges.append(run_async(lambda: companion_client.cancel_shutdown(config), on_done))

    # ---- 와이어가드 ----

    def _on_wireguard_on_clicked(self):
        conf = self.config.load_wireguard_conf()
        if not conf:
            QMessageBox.warning(self, '오류', 'WireGuard 설정이 없습니다. 설정에서 먼저 등록하세요')
            return
        if wireguard_client.is_up():
            self._refresh_status()
            return

        def on_done(result, error):
            if error is not None:
                message = str(error) if isinstance(error, WireGuardError) else f'WireGuard 연결 실패: {error}'
                QMessageBox.warning(self, 'WireGuard', message)
            self._refresh_status()

        self._bridges.append(run_async(lambda: wireguard_client.bring_up(conf), on_done))

    def _on_wireguard_off_clicked(self):
        if not self.config.load_wireguard_conf() or not wireguard_client.is_up():
            self._refresh_status()
            return

        def on_done(result, error):
            if error is not None:
                message = str(error) if isinstance(error, WireGuardError) else f'WireGuard 해제 실패: {error}'
                QMessageBox.warning(self, 'WireGuard', message)
            self._refresh_status()

        self._bridges.append(run_async(wireguard_client.bring_down, on_done))

    # ---- 설정 ----

    def _on_settings_clicked(self):
        dialog = SettingsDialog(self.config, self)
        dialog.exec_()
        self._refresh_status()
