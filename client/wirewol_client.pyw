"""WireWOL 데스크톱 클라이언트 진입점.

android 리모컨 앱과 동일한 기능(PC 켜기/끄기, 와이어가드 켜기/끄기)을
노트북 등 다른 컴퓨터에서 쓸 수 있게 한다. windows/wirewol.pyw(PC 쪽
상주 프로그램)와는 별개의 프로그램이다 — 이 클라이언트는 명령을 "보내는"
쪽이고, wirewol.pyw는 그 명령을 "받는" 쪽이다.
"""
import sys

from PyQt5.QtWidgets import QApplication

from app.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
