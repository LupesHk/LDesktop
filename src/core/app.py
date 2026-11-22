
import sys

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QSystemTrayIcon,
    QMenu,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QStyle
)

from PySide6.QtGui import QAction
from PySide6.QtCore import Qt

import keyboard
import sys
import signal

from replay.recorder import ReplayRecorder
from modules.capture import capture_screen
from modules.link_window import LinkWindow
from core.update_config import APP_VERSION
from core.update_checker import UpdateWorker
from core.update_config import UPDATE_CHECK_ON_STARTUP


class LDesktop(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("L Desktop")
        self.setFixedSize(340, 420)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        self.setStyleSheet("""
            QWidget {
                background-color: #15151f;
                color: #f2f2f7;
                font-family: Segoe UI;
            }

            QLabel#title {
                font-size: 22px;
                font-weight: bold;
            }

            QLabel#subtitle {
                color: #9292a5;
                font-size: 11px;
            }

            QPushButton {
                background-color: #242438;
                border: 1px solid #34344d;
                border-radius: 9px;
                padding: 12px;
                text-align: left;
                font-size: 13px;
            }

            QPushButton:hover {
                background-color: #343450;
            }
        """)

        self.recorder = ReplayRecorder()

        self.setup_ui()
        self.setup_tray()

        self.hotkey_id = keyboard.add_hotkey(
            "F8",
            self.capture_with_hotkey
        )

        self.replay_hotkey_id = keyboard.add_hotkey(
            "F9",
            self.save_replay
        )

        try:
            self.recorder.start()
            print("[L DESKTOP] Replay Buffer iniciado automaticamente.")
        except Exception as error:
            print(f"[L DESKTOP] Erro ao iniciar Replay Buffer: {error}")

        print("[L DESKTOP] Atalho F8 registrado.")
        print("[L DESKTOP] Atalho F9 registrado.")

        self.update_worker = None

        if UPDATE_CHECK_ON_STARTUP:
            self.update_worker = UpdateWorker(self)

            self.update_worker.update_available.connect(
                self.on_update_available
            )

            self.update_worker.check_failed.connect(
                self.on_update_check_failed
            )

            self.update_worker.start()


    def on_update_available(self, update):
        print(
            f"[UPDATE] Nova versão disponível: {update.version}"
        )

    def on_update_check_failed(self, error):
        print(f"[UPDATE] Falha na verificação: {error}")

    def cleanup(self):
        print("[L DESKTOP] Encerrando...")

        try:
            keyboard.remove_hotkey(self.hotkey_id)
        except Exception as error:
            print(f"[L DESKTOP] Erro ao remover F8: {error}")

        try:
            keyboard.remove_hotkey(self.replay_hotkey_id)
        except Exception as error:
            print(f"[L DESKTOP] Erro ao remover F9: {error}")
        if self.update_worker and self.update_worker.isRunning():
            self.update_worker.wait(9000)
        try:
            if hasattr(self, "recorder"):
                self.recorder.stop()
        except Exception as error:
            print(f"[L DESKTOP] Erro ao encerrar Replay Buffer: {error}")

        self.tray.hide()
        print("[L DESKTOP] Encerrado.")

    def capture_with_hotkey(self):
        try:
            filepath = capture_screen()
            print(f"[L DESKTOP] Captura realizada: {filepath}")
        except Exception as error:
            print(f"[L DESKTOP] Erro na captura: {error}")

    def toggle_replay(self):
        try:
            if self.recorder.is_running():
                self.recorder.stop()
                print("[L DESKTOP] Replay Buffer encerrado.")
            else:
                self.recorder.start()
                print("[L DESKTOP] Replay Buffer iniciado.")
        except Exception as error:
            print(f"[L DESKTOP] Erro no Replay Buffer: {error}")

    def save_replay(self):
        try:
            print("[L DESKTOP] Preparando replay...")
            filepath = self.recorder.save_replay()
            print(f"[L DESKTOP] Replay salvo: {filepath}")
        except Exception as error:
            print(f"[L DESKTOP] Erro ao salvar replay: {error}")

    def open_link_window(self):
        self.hide()

        window = LinkWindow(self)
        window.exec()

        self.show_panel()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        header = QHBoxLayout()

        title = QLabel("L Desktop")
        title.setObjectName("title")

        close_button = QPushButton("×")
        close_button.setFixedSize(30, 30)
        close_button.clicked.connect(self.hide)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_button)

        layout.addLayout(header)

        subtitle = QLabel("SEU COMPANHEIRO NO WINDOWS")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        layout.addSpacing(12)

        status = QLabel("●  Aplicativo iniciado")
        status.setStyleSheet("color: #64d69a;")
        layout.addWidget(status)

        layout.addSpacing(15)
        layout.addWidget(QLabel("FERRAMENTAS"))

        for name in [
            "Capturar tela",
            "Histórico de capturas",
            "Conexão com o L",
            "Monitor do computador"
        ]:
            button = QPushButton(name)

            if name == "Capturar tela":
                button.clicked.connect(self.capture_with_hotkey)
            elif name == "Conexão com o L":
                button.clicked.connect(self.open_link_window)

            layout.addWidget(button)

        layout.addStretch()

        footer = QLabel(f"L Desktop • Versão {APP_VERSION}")
        footer.setObjectName("subtitle")
        layout.addWidget(footer)

    def setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("L Desktop")

        self.tray.setIcon(
            QApplication.style().standardIcon(
                QStyle.StandardPixmap.SP_ComputerIcon
            )
        )

        menu = QMenu()

        open_action = QAction("Abrir L Desktop", self)
        open_action.triggered.connect(self.show_panel)

        exit_action = QAction("Encerrar", self)
        exit_action.triggered.connect(QApplication.quit)

        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_clicked)
        self.tray.show()

    def tray_clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_panel()

    def show_panel(self):
        if self.isVisible():
            self.hide()
            return

        screen = QApplication.primaryScreen()
        geometry = screen.availableGeometry()

        self.move(
            geometry.right() - self.width() - 15,
            geometry.bottom() - self.height() - 15
        )

        self.show()
        self.raise_()
        self.activateWindow()



def main():
    app = QApplication(sys.argv)

    app.setApplicationName("L Desktop")
    app.setQuitOnLastWindowClosed(False)

    window = LDesktop()

    app.aboutToQuit.connect(window.cleanup)

    # Permite que o Python processe Ctrl+C durante o loop do Qt.
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    # Mantém o tratamento de sinais ativo sem bloquear a interface.
    from PySide6.QtCore import QTimer

    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(200)

    sys.exit(app.exec())



if __name__ == "__main__":
    main()