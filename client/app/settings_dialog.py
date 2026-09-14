"""자주 안 쓰는 설정들을 모은 화면 — android/.../SettingsActivity.kt와 동일한
구성(PC 등록, WireGuard 설정, 원격 WOL 설정, 전체 초기화)을 데스크톱에 옮긴
것. "PC 등록"은 android 쪽과 마찬가지로 원래 "연결 정보"와 "MAC 수동 입력"
두 그룹이었지만, 후자가 QR로 받은 MAC이 잘못된 어댑터를 가리킬 때만 쓰는
보정용이라 하나로 합쳤다(직접 입력 창에서 host/port/token/mac을 전부 고칠
수 있어 예전 MAC 전용 입력의 상위 호환)."""
import json

from PyQt5.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from app.config import ClientConfig
from app.qr_scan import QrScanDialog, decode_qr_from_file


class SettingsDialog(QDialog):
    def __init__(self, config: ClientConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle('설정')
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_pairing_group())
        layout.addWidget(self._build_wireguard_group())
        layout.addWidget(self._build_router_wol_group())

        reset_button = QPushButton('전체 초기화')
        reset_button.clicked.connect(self._on_reset)
        layout.addWidget(reset_button)

        self._refresh_statuses()

    # ---- PC 등록(연결 정보 + MAC) ----

    def _build_pairing_group(self) -> QGroupBox:
        group = QGroupBox('PC 등록 (필수)')
        v = QVBoxLayout(group)
        self.pairing_status_label = QLabel()
        v.addWidget(self.pairing_status_label)

        self.pairing_json_edit = QPlainTextEdit()
        self.pairing_json_edit.setPlaceholderText(
            '트레이 "연결 정보 보기" QR이나, 안드로이드 앱 설정의 "QR로 설정 내보내기" JSON을 붙여넣으세요')
        self.pairing_json_edit.setFixedHeight(70)
        v.addWidget(self.pairing_json_edit)

        row = QHBoxLayout()
        apply_button = QPushButton('붙여넣은 내용 적용')
        apply_button.clicked.connect(self._on_apply_pairing_json)
        scan_button = QPushButton('웹캠으로 QR 스캔')
        scan_button.clicked.connect(self._on_scan_pairing_qr)
        file_button = QPushButton('이미지 파일에서 QR 불러오기')
        file_button.clicked.connect(self._on_load_pairing_qr_file)
        manual_button = QPushButton('직접 입력')
        manual_button.clicked.connect(self._on_manual_pairing_entry)
        row.addWidget(apply_button)
        row.addWidget(scan_button)
        row.addWidget(file_button)
        row.addWidget(manual_button)
        v.addLayout(row)
        return group

    def _on_apply_pairing_json(self):
        self._apply_pairing_json(self.pairing_json_edit.toPlainText())

    def _on_scan_pairing_qr(self):
        dialog = QrScanDialog(self)
        if dialog.exec_() == QDialog.Accepted and dialog.result_text:
            self._apply_pairing_json(dialog.result_text)

    def _on_load_pairing_qr_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'QR 이미지 선택', '', '이미지 파일 (*.png *.jpg *.jpeg *.bmp)')
        if not path:
            return
        decoded = decode_qr_from_file(path)
        if not decoded:
            QMessageBox.warning(self, '오류', '선택한 이미지에서 QR 코드를 찾을 수 없습니다')
            return
        self._apply_pairing_json(decoded)

    # QR 없이 host/port/token/mac을 직접 입력하는 창 — 예전 "MAC 수동 입력"의
    # 상위 호환(전체 필드를 고칠 수 있음). android의 "PC 등록 → 직접 입력"과
    # 동일한 역할.
    def _on_manual_pairing_entry(self):
        pairing = self.config.load_pairing() or {}
        dialog = QDialog(self)
        dialog.setWindowTitle('PC 등록 (직접 입력)')
        form = QFormLayout(dialog)
        host_edit = QLineEdit(pairing.get('host', ''))
        port_edit = QLineEdit(str(pairing.get('port', '')))
        token_edit = QLineEdit(pairing.get('token', ''))
        mac_edit = QLineEdit(pairing.get('mac', ''))
        form.addRow('PC 주소 (IP)', host_edit)
        form.addRow('포트', port_edit)
        form.addRow('토큰', token_edit)
        form.addRow('MAC 주소', mac_edit)
        buttons = QHBoxLayout()
        save_button = QPushButton('저장')
        cancel_button = QPushButton('취소')
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        form.addRow(buttons)
        cancel_button.clicked.connect(dialog.reject)

        def on_save():
            host = host_edit.text().strip()
            port_text = port_edit.text().strip()
            token = token_edit.text().strip()
            mac = mac_edit.text().strip()
            if not host or not port_text or not token:
                QMessageBox.warning(dialog, '오류', 'PC 주소/포트/토큰을 입력하세요')
                return
            try:
                port = int(port_text)
            except ValueError:
                QMessageBox.warning(dialog, '오류', '포트는 숫자여야 합니다')
                return
            self.config.save_pairing(host, port, token, mac)
            dialog.accept()

        save_button.clicked.connect(on_save)
        if dialog.exec_() == QDialog.Accepted:
            QMessageBox.information(self, '완료', '연결 정보를 저장했습니다')
            self._refresh_statuses()

    def _apply_pairing_json(self, text: str):
        """PC 트레이 QR({host,port,token,mac})과 안드로이드 앱의 "QR로 설정
        내보내기"(위 필드에 더해 wireguard_conf/router_wol을 선택적으로
        포함)를 모두 받아들인다 — 뒤쪽 필드가 있으면 WireGuard/원격 WOL 설정
        칸도 함께 채운다."""
        try:
            data = json.loads(text)
            host, port, token = data['host'], int(data['port']), data['token']
        except (ValueError, KeyError, TypeError):
            QMessageBox.warning(self, '오류', '연결 정보 형식이 올바르지 않습니다')
            return
        mac = data.get('mac', '')
        self.config.save_pairing(host, port, token, mac)

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
        file_button = QPushButton('이미지 파일에서 QR 불러오기')
        file_button.clicked.connect(self._on_load_wireguard_qr_file)
        clear_button = QPushButton('삭제')
        clear_button.clicked.connect(self._on_clear_wireguard_conf)
        row.addWidget(apply_button)
        row.addWidget(scan_button)
        row.addWidget(file_button)
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

    def _on_load_wireguard_qr_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'QR 이미지 선택', '', '이미지 파일 (*.png *.jpg *.jpeg *.bmp)')
        if not path:
            return
        decoded = decode_qr_from_file(path)
        if not decoded:
            QMessageBox.warning(self, '오류', '선택한 이미지에서 QR 코드를 찾을 수 없습니다')
            return
        self.wireguard_conf_edit.setPlainText(decoded)
        self._apply_wireguard_conf(decoded)

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
