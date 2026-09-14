"""웹캠으로 QR 코드를 스캔하는 모달 창 — 트레이가 보여주는 페어링/WireGuard
QR을 PC 카메라로 직접 찍어 입력할 수 있게 한다(붙여넣기가 번거로울 때의
대안 경로)."""
import io

import cv2
import qrcode
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout
from pyzbar.pyzbar import decode as decode_qr


def decode_qr_from_file(path: str) -> str | None:
    """카메라 대신 이미 갖고 있는 QR 이미지 파일(스크린샷 등)에서 바로
    읽어온다 — android 앱의 "갤러리에서 QR 이미지 불러오기"에 대응."""
    image = cv2.imread(path)
    if image is None:
        return None
    codes = decode_qr(image)
    if not codes:
        return None
    return codes[0].data.decode('utf-8', errors='replace')


def generate_qr_pixmap(text: str, size: int = 280) -> QPixmap:
    """android의 "QR로 설정 내보내기"에 대응 — 저장된 설정을 다른 기기가
    다시 스캔할 수 있는 QR 이미지로 만든다(windows/ 트레이의 _pairing_payload
    와 동일하게 qrcode 패키지를 쓴다)."""
    img = qrcode.make(text).resize((size, size))
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue(), 'PNG')
    return pixmap


class QrScanDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('QR 코드 스캔')
        self.result_text: str | None = None

        self._label = QLabel('카메라를 QR 코드에 비춰주세요')
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setMinimumSize(480, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)

        self._capture = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self._capture.isOpened():
            self._label.setText('카메라를 열 수 없습니다')
            return

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_frame)
        self._timer.start(80)

    def _on_frame(self):
        ok, frame = self._capture.read()
        if not ok:
            return
        codes = decode_qr(frame)
        if codes:
            self.result_text = codes[0].data.decode('utf-8', errors='replace')
            self.accept()
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        image = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self._label.setPixmap(QPixmap.fromImage(image).scaled(
            self._label.width(), self._label.height(), Qt.KeepAspectRatio))

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)

    def done(self, result):
        self._cleanup()
        super().done(result)

    def _cleanup(self):
        if hasattr(self, '_timer'):
            self._timer.stop()
        if hasattr(self, '_capture') and self._capture.isOpened():
            self._capture.release()
