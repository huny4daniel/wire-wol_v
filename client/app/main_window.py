"""WireWOL 데스크톱 리모컨 메인 창 — android/.../MainActivity.kt의 버튼
구성(PC 켜기/PC 끄기/예약 끄기/와이어가드 켜기/와이어가드 끄기)과 상태
카드를 그대로 옮긴 것.

와이어가드는 토글 버튼 하나가 아니라 켜기/끄기 버튼을 따로 둔다 — 안드로이드
쪽과 동일하게 사용자가 누른 상태를 그대로 유지하며(창을 최소화하거나
백그라운드로 보내도 자동으로 끄지 않음), 데스크톱 리모컨의 다른 버튼들과
같은 조작 방식을 유지하기 위함이다.
"""
import threading

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

_POWER_ON_POLL_INTERVAL_MS = 5_000
_QUICK_SHUTDOWN_SECONDS = 10


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
        self._power_poll_timer.timeout.connect(self._poll_power_status)

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

        self._pending_shutdown_target = None
        self._refresh_status()

    # ---- 상태 표시 ----

    def _refresh_status(self):
        pairing = self.config.load_pairing()
        self.status_host_label.setText(
            f'대상: {pairing["host"]}:{pairing["port"]}' if pairing else '대상: 연결 정보 없음')
        mac = (pairing or {}).get('mac', '')
        self.status_mac_label.setText(f'MAC: {mac}' if mac else 'MAC: 없음')
        self._refresh_wireguard_status()
        self._check_power_status(pairing)

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
        self.status_power_label.setText('전원: 확인 중...')
        config = CompanionConfig(pairing['host'], pairing['port'], pairing['token'])

        def on_done(result, error):
            if error is None:
                self.status_power_label.setText('전원: 켜짐')
                if on_result:
                    on_result(True)
            else:
                self.status_power_label.setText('전원: 꺼짐/확인 불가')
                if on_result:
                    on_result(False)

        self._bridges.append(run_async(lambda: companion_client.ping(config), on_done))

    # ---- PC 켜기 ----

    def _on_power_on_clicked(self):
        pairing = self.config.load_pairing()
        mac = (pairing or {}).get('mac', '')
        if not mac:
            QMessageBox.warning(self, '오류', 'MAC 주소가 없어 PC를 깨울 수 없습니다. 설정에서 연결 정보를 다시 확인하세요')
            return
        try:
            wol.send_magic_packet(mac)
        except ValueError as e:
            QMessageBox.warning(self, '오류', str(e))
            return
        self._trigger_remote_wake_if_configured(mac)
        QMessageBox.information(self, 'PC 켜기', '깨우기 신호를 보냈습니다')
        self._start_power_on_polling(pairing)

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
        self._power_poll_timer.start(_POWER_ON_POLL_INTERVAL_MS)

    def _poll_power_status(self):
        pairing = self.config.load_pairing()

        def on_result(is_on):
            if is_on:
                self._power_poll_timer.stop()

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
        config = CompanionConfig(pairing['host'], pairing['port'], pairing['token'])

        def on_done(result, error):
            if error is not None:
                message = str(error) if isinstance(error, CompanionError) else f'종료 요청 실패: {error}'
                QMessageBox.warning(self, '오류', message)
                return
            self._on_shutdown_scheduled(delay_seconds or _QUICK_SHUTDOWN_SECONDS, pairing)

        self._bridges.append(run_async(lambda: companion_client.shutdown(config, delay_seconds), on_done))

    def _on_shutdown_scheduled(self, delay_seconds, pairing):
        if delay_seconds <= _QUICK_SHUTDOWN_SECONDS:
            reply = QMessageBox(self)
            reply.setWindowTitle('PC 끄기')
            reply.setText(f'{delay_seconds}초 후 종료됩니다')
            cancel_button = reply.addButton('취소', QMessageBox.ActionRole)
            reply.addButton(QMessageBox.Ok)
            reply.exec_()
            if reply.clickedButton() == cancel_button:
                self._cancel_pending_shutdown(pairing)
                return
        else:
            minutes = delay_seconds // 60
            QMessageBox.information(self, 'PC 끄기', f'{minutes}분 후 종료가 예약되었습니다')
        self.status_shutdown_label.setText('예약된 종료가 있습니다 (클릭하여 취소)')
        self.status_shutdown_label.show()
        try:
            self.status_shutdown_label.mousePressEvent = lambda event: self._cancel_pending_shutdown(pairing)
        except Exception:
            pass

    def _cancel_pending_shutdown(self, pairing):
        config = CompanionConfig(pairing['host'], pairing['port'], pairing['token'])

        def on_done(result, error):
            if error is not None:
                message = str(error) if isinstance(error, CompanionError) else f'취소 실패: {error}'
                QMessageBox.warning(self, '오류', message)
                return
            self.status_shutdown_label.hide()
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
