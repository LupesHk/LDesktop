
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
    QStyle,
    QMessageBox,
    QProgressDialog,
)

from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QTimer

import keyboard
import sys
import signal
import os
import shutil
import ctypes
import subprocess

from pathlib import Path
from replay.recorder import ReplayRecorder
from modules.capture import capture_screen
from modules.link_window import LinkWindow
from core.update_config import APP_VERSION
from core.update_config import UPDATE_CHECK_ON_STARTUP
from ctypes import wintypes

from core.update_checker import (
    UpdateWorker,
    UpdateDownloadWorker
)

from core.paths import DATA_DIR

def confirm_update_startup():
    event_name = os.environ.get(
        "LDESKTOP_UPDATE_CONFIRMATION"
    )

    if not event_name:
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    EVENT_MODIFY_STATE = 0x0002

    kernel32.OpenEventW.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.OpenEventW.restype = wintypes.HANDLE

    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenEventW(
        EVENT_MODIFY_STATE,
        False,
        event_name
    )

    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        if not kernel32.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)

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

        if not getattr(sys, "frozen", False):
            print(
                f"[UPDATE] Versão disponível: {update.version}. "
                "Instalação automática disponível somente no executável."
            )
            return

        answer = QMessageBox.question(
            self,
            "Atualização disponível",
            (
                f"Uma nova versão do L Desktop está disponível.\n\n"
                f"Versão atual: {APP_VERSION}\n"
                f"Nova versão: {update.version}\n\n"
                f"{update.notes}\n\n"
                "Deseja baixar a atualização?"
            ),
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if answer == QMessageBox.StandardButton.Yes:
            self.start_update_download(update)


    def start_update_download(self, update):

        self.update_progress = QProgressDialog(
            "Baixando atualização...",
            "Cancelar",
            0,
            100,
            self
        )

        self.update_progress.setWindowTitle(
            "Atualizando L Desktop"
        )

        self.update_progress.setWindowModality(
            Qt.WindowModality.WindowModal
        )

        self.update_progress.setAutoClose(False)
        self.update_progress.setAutoReset(False)
        self.update_progress.setValue(0)

        self.download_worker = UpdateDownloadWorker(
            update,
            self
        )

        self.download_worker.progress.connect(
            self.update_progress.setValue
        )

        self.download_worker.download_ready.connect(
            self.on_update_download_ready
        )

        self.download_worker.download_failed.connect(
            self.on_update_download_failed
        )

        self.update_progress.canceled.connect(
            self.download_worker.requestInterruption
        )

        self.download_worker.start()
        self.update_progress.show()


    def on_update_download_failed(self, error):

        self.update_progress.close()

        QMessageBox.warning(
            self,
            "Falha na atualização",
            f"Não foi possível baixar a atualização:\n\n{error}"
        )


    def on_update_download_ready(self, installer_path):

        self.update_progress.close()

        if self.download_worker:
            self.download_worker.wait()

        installer = Path(installer_path).resolve()

        updater_source = (
            DATA_DIR / "updater" / "LDesktopUpdater.exe"
        )

        local_appdata = Path(
            os.environ.get("LOCALAPPDATA", Path.home())
        )

        update_dir = local_appdata / "LDesktop" / "updates"
        update_dir.mkdir(parents=True, exist_ok=True)

        updater_target = update_dir / "LDesktopUpdater.exe"

        try:
            if not updater_source.is_file():
                raise FileNotFoundError(
                    f"Atualizador não encontrado: {updater_source}"
                )

            shutil.copy2(
                updater_source,
                updater_target
            )

            QMessageBox.information(
                self,
                "Atualização pronta",
                "O L Desktop será encerrado para instalar a atualização."
            )

            subprocess.Popen(
                [
                    str(updater_target),
                    "--parent-pid",
                    str(os.getpid()),
                    "--installer",
                    str(installer),
                    "--app-exe",
                    str(Path(sys.executable).resolve())
                ],
                cwd=str(update_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS
            )

            from PySide6.QtWidgets import QApplication
            QApplication.quit()

        except Exception as error:
            QMessageBox.critical(
                self,
                "Erro ao iniciar atualização",
                str(error)
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

        try:
            if self.update_worker and self.update_worker.isRunning():
                self.update_worker.requestInterruption()
                self.update_worker.wait()
        except Exception as error:
            print(f"[L DESKTOP] Erro ao encerrar verificação de atualização: {error}")

        try:
            if (
                hasattr(self, "download_worker")
                and self.download_worker
                and self.download_worker.isRunning()
            ):
                self.download_worker.requestInterruption()
                self.download_worker.wait()
        except Exception as error:
            print(f"[L DESKTOP] Erro ao encerrar download: {error}")

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

    QTimer.singleShot(2000, confirm_update_startup)

    app.aboutToQuit.connect(window.cleanup)

    # Permite que o Python processe Ctrl+C durante o loop do Qt.
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    # Mantém o tratamento de sinais ativo sem bloquear a interface.

    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(200)

    sys.exit(app.exec())



if __name__ == "__main__":
    main()