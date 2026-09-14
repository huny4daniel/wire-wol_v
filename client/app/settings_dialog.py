"""자주 안 쓰는 설정들을 모은 화면 — android/.../SettingsActivity.kt와 동일한
구성(연결 정보, MAC 수동 입력, WireGuard 설정, 원격 WOL 설정, 전체 초기화)을
데스크톱에 옮긴 것."""
import json

from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from app.config import ClientConfig
from app.qr_scan import QrScanDialog


class SettingsDialog(QDialog):
    def __init__(self, config: ClientConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle('설정')
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_pairing_group())
        layout.addWidget(self._build_mac_group())
        layout.addWidget(self._build_wireguard_group())
        layout.addWidget(self._build_router_wol_group())

        reset_button = QPushButton('전체 초기화')
        reset_button.clicked.connect(self._on_reset)
        layout.addWidget(reset_button)

        self._refresh_statuses()

    # ---- 연결 정보(페어링) ----

    def _build_pairing_group(self) -> QGroupBox:
        group = QGroupBox('연결 정보 (필수)')
        v = QVBoxLayout(group)
        self.pairing_status_label = QLabel()
        v.addWidget(self.pairing_status_label)

        self.pairing_json_edit = QPlainTextEdit()
        self.pairing_json_edit.setPlaceholderText(
            '트레이 "연결 정보 보기" QR이나, 안드로이드 앱 설정의 "전체 설정 QR로 보여주기" JSON을 붙여넣으세요')
        self.pairing_json_edit.setFixedHeight(70)
        v.addWidget(self.pairing_json_edit)

        row = QHBoxLayout()
        apply_button = QPushButton('붙여넣은 내용 적용')
        apply_button.clicked.connect(self._on_apply_pairing_json)
        scan_button = QPushButton('웹캠으로 QR 스캔')
        scan_button.clicked.connect(self._on_scan_pairing_qr)
        row.addWidget(apply_button)
        row.addWidget(scan_button)
        v.addLayout(row)
        return group

    def _on_apply_pairing_json(self):
        self._apply_pairing_json(self.pairing_json_edit.toPlainText())

    def _on_scan_pairing_qr(self):
        dialog = QrScanDialog(self)
        if dialog.exec_() == QDialog.Accepted and dialog.result_text:
            self._apply_pairing_json(dialog.result_text)

    def _apply_pairing_json(self, text: str):
        """PC 트레이 QR({host,port,token,mac})과 안드로이드 앱의 "전체 설정
        QR"(위 필드에 더해 wireguard_conf/router_wol을 선택적으로 포함)을
        모두 받아들인다 — 뒤쪽 필드가 있으면 WireGuard/원격 WOL 설정 칸도
        함께 채운다."""
        try:
            data = json.loads(text)
            host, port, token = data['host'], int(data['port']), data['token']
        except (ValueError, KeyError, TypeError):
            QMessageBox.warning(self, '오류', '연결 정보 형식이 올바르지 않습니다')
            return
        mac = data.get('mac', '')
        self.config.save_pairing(host, port, token, mac)
        if mac:
            self.mac_edit.setText(mac)

        applied_extra = []

        wireguard_conf = data.get('wireguard_conf')
        if isinstance(wireguard_conf, str) and '[Interface]' in wireguard_conf and '[Peer]' in wireguard_conf:
            self.config.save_wireguard_conf(wireguard_conf)
            self.wireguard_conf_edit.setPlainText(wireguard_conf)
            applied_extra.append('WireGuard 설정')

        router_wol = data.get('router_wol')
        if isinstance(router_wol, dict) and all(router_wol.get(k) for k in ('host', 'port', 'id', 'password')):
            self.config.save_router_wol(str(router_wol['host']), str(router_wol['port']), str(router_wol['id']), str(router_wol['password']))
            self.router_host_edit.setText(str(router_wol['host']))
            self.router_port_edit.setText(str(router_wol['port']))
            self.router_id_edit.setText(str(router_wol['id']))
            self.router_password_edit.setText(str(router_wol['password']))
            applied_extra.append('원격 WOL 설정')

        message = '연결 정보를 저장했습니다'
        if applied_extra:
            message += f' ({", ".join(applied_extra)} 포함)'
        QMessageBox.information(self, '완료', message)
        self._refresh_statuses()

    # ---- MAC 수동 입력 ----

    def _build_mac_group(self) -> QGroupBox:
        group = QGroupBox('MAC 주소 수동 입력 (선택)')
        form = QFormLayout(group)
        self.mac_edit = QLineEdit()
        pairing = self.config.load_pairing()
        if pairing:
            self.mac_edit.setText(pairing.get('mac', ''))
        save_button = QPushButton('저장')
        save_button.clicked.connect(self._on_save_mac)
        form.addRow('MAC', self.mac_edit)
        form.addRow('', save_button)
        return group

    def _on_save_mac(self):
        mac = self.mac_edit.text().strip()
        if not mac:
            QMessageBox.warning(self, '오류', 'MAC 주소를 입력하세요')
            return
        self.config.save_mac(mac)
        QMessageBox.information(self, '완료', 'MAC 주소를 저장했습니다')
        self._refresh_statuses()

    # ---- WireGuard 설정 ----

    def _build_wireguard_group(self) -> QGroupBox:
        group = QGroupBox('WireGuard 설정 (선택, 외부에서 접속 시 필요)')
        v = QVBoxLayout(group)
        self.wireguard_status_label = QLabel()
        v.addWidget(self.wireguard_status_label)

        self.wireguard_conf_edit = QPlainTextEdit()
        self.wireguard_conf_edit.setPlaceholderText('공유기가 만들어준 WireGuard 설정(.conf) QR의 텍스트를 붙여넣으세요')
        self.wireguard_conf_edit.setFixedHeight(90)
        conf = self.config.load_wireguard_conf()
        if conf:
            self.wireguard_conf_edit.setPlainText(conf)
        v.addWidget(self.wireguard_conf_edit)

        row = QHBoxLayout()
        apply_button = QPushButton('붙여넣은 내용 적용')
        apply_button.clicked.connect(self._on_apply_wireguard_conf)
        scan_button = QPushButton('웹캠으로 QR 스캔')
        scan_button.clicked.connect(self._on_scan_wireguard_qr)
        clear_button = QPushButton('삭제')
        clear_button.clicked.connect(self._on_clear_wireguard_conf)
        row.addWidget(apply_button)
        row.addWidget(scan_button)
        row.addWidget(clear_button)
        v.addLayout(row)
        return group

    def _on_apply_wireguard_conf(self):
        self._apply_wireguard_conf(self.wireguard_conf_edit.toPlainText())

    def _on_scan_wireguard_qr(self):
        dialog = QrScanDialog(self)
        if dialog.exec_() == QDialog.Accepted and dialog.result_text:
            self.wireguard_conf_edit.setPlainText(dialog.result_text)
            self._apply_wireguard_conf(dialog.result_text)

    def _apply_wireguard_conf(self, text: str):
        text = text.strip()
        if '[Interface]' not in text or '[Peer]' not in text:
            QMessageBox.warning(self, '오류', 'WireGuard 설정 형식이 올바르지 않습니다')
            return
        self.config.save_wireguard_conf(text)
        QMessageBox.information(self, '완료', 'WireGuard 설정을 저장했습니다')
        self._refresh_statuses()

    def _on_clear_wireguard_conf(self):
        self.config.clear_wireguard_conf()
        self.wireguard_conf_edit.clear()
        self._refresh_statuses()

    # ---- 원격 WOL(공유기) ----

    def _build_router_wol_group(self) -> QGroupBox:
        group = QGroupBox('원격 WOL(공유기) 설정 (선택, 외부에서 WireGuard 없이 PC 켜기용)')
        form = QFormLayout(group)
        self.router_status_label = QLabel()
        form.addRow(self.router_status_label)

        router = self.config.load_router_wol() or {}
        self.router_host_edit = QLineEdit(router.get('host', ''))
        self.router_port_edit = QLineEdit(router.get('port', ''))
        self.router_id_edit = QLineEdit(router.get('id', ''))
        self.router_password_edit = QLineEdit(router.get('password', ''))
        self.router_password_edit.setEchoMode(QLineEdit.Password)
        form.addRow('공유기 주소', self.router_host_edit)
        form.addRow('포트', self.router_port_edit)
        form.addRow('아이디', self.router_id_edit)
        form.addRow('비밀번호', self.router_password_edit)

        row = QHBoxLayout()
        save_button = QPushButton('저장')
        save_button.clicked.connect(self._on_save_router_wol)
        clear_button = QPushButton('삭제')
        clear_button.clicked.connect(self._on_clear_router_wol)
        row.addWidget(save_button)
        row.addWidget(clear_button)
        form.addRow(row)
        return group

    def _on_save_router_wol(self):
        host = self.router_host_edit.text().strip()
        port = self.router_port_edit.text().strip()
        user_id = self.router_id_edit.text().strip()
        password = self.router_password_edit.text()
        if not all((host, port, user_id, password)):
            QMessageBox.warning(self, '오류', '모든 항목을 입력하세요')
            return
        self.config.save_router_wol(host, port, user_id, password)
        QMessageBox.information(self, '완료', '원격 WOL 설정을 저장했습니다')
        self._refresh_statuses()

    def _on_clear_router_wol(self):
        self.config.clear_router_wol()
        self.router_host_edit.clear()
        self.router_port_edit.clear()
        self.router_id_edit.clear()
        self.router_password_edit.clear()
        self._refresh_statuses()

    # ---- 전체 초기화 ----

    def _on_reset(self):
        if QMessageBox.question(self, '전체 초기화', '저장된 모든 설정을 삭제할까요?') != QMessageBox.Yes:
            return
        self.config.reset_all()
        self.pairing_json_edit.clear()
        self.mac_edit.clear()
        self.wireguard_conf_edit.clear()
        self.router_host_edit.clear()
        self.router_port_edit.clear()
        self.router_id_edit.clear()
        self.router_password_edit.clear()
        self._refresh_statuses()

    # ---- 상태 문구 ----

    def _refresh_statuses(self):
        pairing = self.config.load_pairing()
        self.pairing_status_label.setText(
            f'설정됨 ({pairing["host"]}:{pairing["port"]})' if pairing else '설정 안 됨')
        conf = self.config.load_wireguard_conf()
        self.wireguard_status_label.setText('설정됨' if conf else '설정 안 됨')
        router = self.config.load_router_wol()
        self.router_status_label.setText('설정됨' if router else '설정 안 됨')
