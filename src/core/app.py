
import sys
import signal
import os
import shutil
import ctypes
import subprocess
import traceback

from pathlib import Path
from ctypes import wintypes

import keyboard

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSize, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QSystemTrayIcon,
    QMenu,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QStyle,
    QMessageBox,
    QProgressDialog,
    QFrame,
    QStackedWidget,
    QListWidget,
    QListWidgetItem,
    QComboBox,
)

from core.audio_config import (
    list_microphones,
    get_default_microphone_info,
    load_audio_settings,
    save_audio_settings,
    test_microphone,
)

from replay.recorder import ReplayRecorder
from modules.capture import (
    capture_screen,
    CaptureQueueWorker,
    queue_replay,
)
from modules.link_window import LinkWindow
from modules.device import get_device_token

from core.update_config import APP_VERSION, UPDATE_CHECK_ON_STARTUP
from core.update_checker import UpdateWorker, UpdateDownloadWorker
from core.paths import DATA_DIR, SAVED_DIR


def confirm_update_startup():
    event_name = os.environ.get("LDESKTOP_UPDATE_CONFIRMATION")

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
        event_name,
    )

    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        if not kernel32.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


class CaptureWorker(QThread):
    completed = Signal(object)

    def run(self):
        try:
            result = capture_screen()
            self.completed.emit(result)
        except Exception as error:
            self.completed.emit(error)

class AudioDeviceTestWorker(QThread):
    completed = Signal(object)

    def __init__(self, microphone_id, parent=None):
        super().__init__(parent)
        self.microphone_id = microphone_id

    def run(self):
        try:
            result = test_microphone(self.microphone_id)
            self.completed.emit(result)

        except Exception as error:
            self.completed.emit({
                "error": str(error)
            })

class LDesktop(QMainWindow):
    capture_requested = Signal()
    replay_requested = Signal()

    def __init__(self):
        super().__init__()

        self.setWindowTitle("L Desktop")
        self.resize(1080, 700)
        self.setMinimumSize(850, 580)

        self.recorder = ReplayRecorder()

        self.capture_worker = None
        self.capture_queue_worker = None
        self.update_worker = None
        self.download_worker = None

        self.hotkey_id = None
        self.replay_hotkey_id = None

        self.pending_count = 0
        self.last_queue_message = "Fila de envios vazia."

        self.capture_requested.connect(self.start_capture)
        self.replay_requested.connect(self.save_replay)
        self.audio_test_worker = None

        self.setup_style()
        self.setup_ui()
        self.setup_tray()

        self.start_capture_queue()
        self.register_hotkeys()
        self.start_replay_buffer()
        self.start_update_checker()

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_runtime_status)
        self.status_timer.start(1500)

        self.refresh_runtime_status()
        self.refresh_replay_history()

    # ---------------------------------------------------------
    # VISUAL
    # ---------------------------------------------------------

    def setup_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget#centralWidget {
                background-color: #11111a;
                color: #f0eff8;
                font-family: "Segoe UI";
                font-size: 13px;
            }

            QFrame#sidebar {
                background-color: #171722;
                border-right: 1px solid #29293a;
            }

            QFrame#brandMark {
                background-color: #7657e8;
                border-radius: 11px;
            }

            QLabel#brandLetter {
                color: white;
                font-size: 23px;
                font-weight: bold;
            }

            QLabel#brandTitle {
                color: #f4f1ff;
                font-size: 20px;
                font-weight: bold;
            }

            QLabel#brandSubtitle {
                color: #89899e;
                font-size: 10px;
                letter-spacing: 1px;
            }

            QLabel#sectionLabel {
                color: #74748b;
                font-size: 10px;
                font-weight: bold;
                padding-left: 9px;
                letter-spacing: 1px;
            }

            QPushButton#navButton {
                background-color: transparent;
                color: #a6a5b9;
                border: none;
                border-radius: 8px;
                padding: 12px 13px;
                text-align: left;
                font-size: 13px;
            }

            QPushButton#navButton:hover {
                background-color: #242437;
                color: white;
            }

            QPushButton#navButton:checked {
                background-color: #30284d;
                color: #c6b9ff;
                border: 1px solid #51417d;
                font-weight: bold;
            }

            QLabel#pageTitle {
                font-size: 25px;
                font-weight: bold;
                color: #f5f3fc;
            }

            QLabel#pageSubtitle {
                color: #9291a8;
                font-size: 12px;
            }

            QFrame#card {
                background-color: #191925;
                border: 1px solid #2d2d40;
                border-radius: 12px;
            }

            QFrame#card:hover {
                border-color: #46405e;
            }

            QLabel#cardTitle {
                color: #9d9cb2;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 0.7px;
            }

            QLabel#cardValue {
                color: #f5f2ff;
                font-size: 22px;
                font-weight: bold;
            }

            QLabel#muted {
                color: #9291a8;
                font-size: 12px;
            }

            QLabel#successText {
                color: #70d6a1;
                font-size: 12px;
                font-weight: bold;
            }

            QLabel#warningText {
                color: #e5bc71;
                font-size: 12px;
                font-weight: bold;
            }

            QPushButton {
                background-color: #252538;
                color: #efedf8;
                border: 1px solid #393950;
                border-radius: 8px;
                padding: 11px 15px;
                font-size: 12px;
                font-weight: bold;
            }

            QPushButton:hover {
                background-color: #33334b;
                border-color: #62528e;
            }

            QPushButton:pressed {
                background-color: #29233e;
            }

            QPushButton#primaryButton {
                background-color: #7657e8;
                color: white;
                border: 1px solid #876cf0;
            }

            QPushButton#primaryButton:hover {
                background-color: #866cf1;
            }

            QPushButton#dangerButton {
                background-color: #41242e;
                color: #f0a6b4;
                border: 1px solid #68404d;
            }

            QListWidget {
                background-color: #191925;
                border: 1px solid #2d2d40;
                border-radius: 9px;
                padding: 7px;
                outline: none;
            }

            QListWidget::item {
                color: #e7e4f2;
                padding: 12px;
                border-radius: 6px;
                border-bottom: 1px solid #29293a;
            }

            QListWidget::item:hover {
                background-color: #28283b;
            }

            QListWidget::item:selected {
                background-color: #30284d;
                color: #d2c8ff;
            }

            QProgressDialog {
                background-color: #191925;
                color: white;
            }
        """)

    def setup_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Barra lateral
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(225)

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(17, 22, 17, 18)
        sidebar_layout.setSpacing(9)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(11)

        brand_mark = QFrame()
        brand_mark.setObjectName("brandMark")
        brand_mark.setFixedSize(42, 42)

        brand_mark_layout = QVBoxLayout(brand_mark)
        brand_mark_layout.setContentsMargins(0, 0, 0, 0)

        brand_letter = QLabel("L")
        brand_letter.setObjectName("brandLetter")
        brand_letter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark_layout.addWidget(brand_letter)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)

        brand_title = QLabel("L Desktop")
        brand_title.setObjectName("brandTitle")

        brand_subtitle = QLabel("COMPANION FOR WINDOWS")
        brand_subtitle.setObjectName("brandSubtitle")

        brand_text.addWidget(brand_title)
        brand_text.addWidget(brand_subtitle)

        brand_row.addWidget(brand_mark)
        brand_row.addLayout(brand_text)
        brand_row.addStretch()

        sidebar_layout.addLayout(brand_row)
        sidebar_layout.addSpacing(28)

        section = QLabel("ESPAÇO DE TRABALHO")
        section.setObjectName("sectionLabel")
        sidebar_layout.addWidget(section)

        self.nav_buttons = []

        navigation = [
            ("◈   Visão geral", 0),
            ("▶   Replays", 1),
            ("⚙   Configurações", 2),
        ]

        for title, index in navigation:
            button = QPushButton(title)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

            button.clicked.connect(
                lambda checked=False, page=index: self.navigate(page)
            )

            sidebar_layout.addWidget(button)
            self.nav_buttons.append(button)

        sidebar_layout.addStretch()

        sidebar_status = QFrame()
        sidebar_status.setObjectName("card")

        sidebar_status_layout = QVBoxLayout(sidebar_status)
        sidebar_status_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_status_layout.setSpacing(5)

        sidebar_status_title = QLabel("L DESKTOP")
        sidebar_status_title.setObjectName("cardTitle")

        self.sidebar_status_label = QLabel("Inicializando...")
        self.sidebar_status_label.setObjectName("successText")

        sidebar_status_layout.addWidget(sidebar_status_title)
        sidebar_status_layout.addWidget(self.sidebar_status_label)

        sidebar_layout.addWidget(sidebar_status)

        version = QLabel(f"Versão {APP_VERSION}")
        version.setObjectName("muted")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addSpacing(12)
        sidebar_layout.addWidget(version)

        root.addWidget(self.sidebar)

        # Área principal
        main_area = QWidget()
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(28, 23, 28, 24)
        main_layout.setSpacing(19)

        topbar = QHBoxLayout()

        self.current_page_title = QLabel("Visão geral")
        self.current_page_title.setObjectName("pageTitle")

        topbar.addWidget(self.current_page_title)
        topbar.addStretch()

        connection_button = QPushButton("Conexão Discord")
        connection_button.clicked.connect(self.open_link_window)
        topbar.addWidget(connection_button)

        main_layout.addLayout(topbar)

        self.page_stack = QStackedWidget()

        self.page_stack.addWidget(self.build_overview_page())
        self.page_stack.addWidget(self.build_replays_page())
        self.page_stack.addWidget(self.build_settings_page())

        main_layout.addWidget(self.page_stack)

        root.addWidget(main_area, 1)

        self.navigate(0)

    def page_container(self, title, subtitle):
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(17)

        description = QLabel(subtitle)
        description.setObjectName("pageSubtitle")

        layout.addWidget(description)

        return page, layout

    def create_card(self, title, value, description):
        card = QFrame()
        card.setObjectName("card")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(17, 16, 17, 16)
        layout.setSpacing(8)

        heading = QLabel(title.upper())
        heading.setObjectName("cardTitle")

        value_label = QLabel(value)
        value_label.setObjectName("cardValue")

        description_label = QLabel(description)
        description_label.setObjectName("muted")
        description_label.setWordWrap(True)

        layout.addWidget(heading)
        layout.addWidget(value_label)
        layout.addWidget(description_label)
        layout.addStretch()

        return card, value_label, description_label

    def build_overview_page(self):
        page, layout = self.page_container(
            "Visão geral",
            "Acompanhe o estado do L Desktop e acesse suas ferramentas."
        )

        grid = QGridLayout()
        grid.setSpacing(13)

        replay_card, self.replay_status_label, self.replay_detail_label = (
            self.create_card(
                "Replay Buffer",
                "Inicializando",
                "Captura contínua dos últimos 30 segundos."
            )
        )

        audio_card, self.audio_status_label, self.audio_detail_label = (
            self.create_card(
                "Áudio",
                "Inicializando",
                "Captura de áudio do sistema e diagnóstico do microfone."
            )
        )

        discord_card, self.discord_status_label, self.discord_detail_label = (
            self.create_card(
                "Discord",
                "Verificando",
                "Estado da conexão do dispositivo."
            )
        )

        queue_card, self.queue_status_label, self.queue_detail_label = (
            self.create_card(
                "Fila de envios",
                "0",
                "Arquivos aguardando confirmação do servidor."
            )
        )

        grid.addWidget(replay_card, 0, 0)
        grid.addWidget(audio_card, 0, 1)
        grid.addWidget(discord_card, 1, 0)
        grid.addWidget(queue_card, 1, 1)

        layout.addLayout(grid)

        recent_card = QFrame()
        recent_card.setObjectName("card")

        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(17, 14, 17, 14)
        recent_layout.setSpacing(6)

        recent_title = QLabel("ÚLTIMO REPLAY")
        recent_title.setObjectName("cardTitle")

        self.last_replay_label = QLabel("Nenhum replay salvo nesta sessão.")
        self.last_replay_label.setObjectName("muted")
        self.last_replay_label.setWordWrap(True)

        recent_layout.addWidget(recent_title)
        recent_layout.addWidget(self.last_replay_label)

        layout.addWidget(recent_card)
        layout.addStretch()

        return page

    def build_replays_page(self):
        page, layout = self.page_container(
            "Replays",
            "Consulte os vídeos salvos e acompanhe o envio automático."
        )

        card = QFrame()
        card.setObjectName("card")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(17, 15, 17, 15)
        card_layout.setSpacing(9)

        title = QLabel("Histórico de replays")
        title.setObjectName("cardTitle")

        description = QLabel(
            "Os arquivos originais permanecem no computador, "
            "mesmo depois do envio ao Discord."
        )
        description.setObjectName("muted")

        self.replay_list = QListWidget()
        self.replay_list.itemDoubleClicked.connect(self.open_replay_item)

        card_layout.addWidget(title)
        card_layout.addWidget(description)
        card_layout.addWidget(self.replay_list, 1)

        layout.addWidget(card, 1)

        actions = QHBoxLayout()

        refresh_button = QPushButton("Atualizar")
        refresh_button.clicked.connect(self.refresh_replay_history)

        folder_button = QPushButton("Abrir pasta")
        folder_button.clicked.connect(self.open_replay_folder)

        actions.addWidget(refresh_button)
        actions.addWidget(folder_button)
        actions.addStretch()

        layout.addLayout(actions)

        return page


    def build_settings_page(self):
        page, layout = self.page_container(
            "Configurações",
            "Personalize o funcionamento do L Desktop."
        )

        # ÁUDIO
        audio_card = QFrame()
        audio_card.setObjectName("card")

        audio_layout = QVBoxLayout(audio_card)
        audio_layout.setContentsMargins(18, 17, 18, 17)
        audio_layout.setSpacing(11)

        audio_title = QLabel("ÁUDIO E MICROFONE")
        audio_title.setObjectName("cardTitle")

        audio_description = QLabel(
            "Selecione o microfone que será utilizado nos replays."
        )
        audio_description.setObjectName("muted")
        audio_description.setWordWrap(True)

        self.microphone_combo = QComboBox()
        self.microphone_combo.setMinimumHeight(40)

        refresh_button = QPushButton("Atualizar dispositivos")
        refresh_button.clicked.connect(
            self.refresh_microphone_devices
        )

        test_button = QPushButton("Testar microfone")
        test_button.setObjectName("primaryButton")
        self.microphone_test_button = test_button
        test_button.clicked.connect(
            self.test_selected_microphone
        )

        self.audio_test_status = QLabel(
            "Selecione um microfone para começar."
        )
        self.audio_test_status.setObjectName("muted")
        self.audio_test_status.setWordWrap(True)

        audio_buttons = QHBoxLayout()
        audio_buttons.addWidget(refresh_button)
        audio_buttons.addWidget(test_button)

        save_buttons = QHBoxLayout()

        apply_button = QPushButton("Salvar e aplicar")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(
            self.apply_microphone_selection
        )

        save_buttons.addWidget(apply_button)

        audio_layout.addWidget(audio_title)
        audio_layout.addWidget(audio_description)
        audio_layout.addWidget(self.microphone_combo)
        audio_layout.addLayout(audio_buttons)
        audio_layout.addLayout(save_buttons)
        audio_layout.addWidget(self.audio_test_status)

        layout.addWidget(audio_card)

        self.refresh_microphone_devices()

        # ATALHOS
        shortcuts = QFrame()
        shortcuts.setObjectName("card")

        shortcuts_layout = QVBoxLayout(shortcuts)
        shortcuts_layout.setContentsMargins(18, 17, 18, 17)
        shortcuts_layout.setSpacing(13)

        shortcuts_title = QLabel("ATALHOS DE TECLADO")
        shortcuts_title.setObjectName("cardTitle")
        shortcuts_layout.addWidget(shortcuts_title)

        shortcuts_layout.addLayout(
            self.shortcut_row("F8", "Capturar tela")
        )

        shortcuts_layout.addLayout(
            self.shortcut_row(
                "F9",
                "Salvar os últimos 30 segundos"
            )
        )

        layout.addWidget(shortcuts)

        # ARMAZENAMENTO
        storage = QFrame()
        storage.setObjectName("card")

        storage_layout = QVBoxLayout(storage)
        storage_layout.setContentsMargins(18, 17, 18, 17)
        storage_layout.setSpacing(9)

        storage_title = QLabel("ARMAZENAMENTO")
        storage_title.setObjectName("cardTitle")

        storage_path = QLabel(str(DATA_DIR))
        storage_path.setObjectName("muted")
        storage_path.setWordWrap(True)
        storage_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        folder_button = QPushButton("Abrir pasta de dados")
        folder_button.clicked.connect(
            self.open_data_folder
        )

        storage_layout.addWidget(storage_title)
        storage_layout.addWidget(storage_path)
        storage_layout.addWidget(folder_button)

        layout.addWidget(storage)
        layout.addStretch()

        return page


    def shortcut_row(self, key, description):
        row = QHBoxLayout()

        key_label = QLabel(key)
        key_label.setFixedWidth(58)
        key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        key_label.setStyleSheet("""
            QLabel {
                background-color: #30284d;
                color: #d0c4ff;
                border: 1px solid #51417d;
                border-radius: 6px;
                padding: 7px;
                font-weight: bold;
            }
        """)

        description_label = QLabel(description)
        description_label.setObjectName("muted")

        row.addWidget(key_label)
        row.addWidget(description_label)
        row.addStretch()

        return row

    def navigate(self, index):
        self.page_stack.setCurrentIndex(index)

        titles = [
            "Visão geral",
            "Replays",
            "Configurações",
        ]

        self.current_page_title.setText(titles[index])

        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)

        if index == 1:
            self.refresh_replay_history()
    # ---------------------------------------------------------
    # ESTADO E ATUALIZAÇÃO VISUAL
    # ---------------------------------------------------------

    def refresh_runtime_status(self):
        running = self.recorder.is_running()

        if running:
            self.replay_status_label.setText("Ativo")
            self.replay_status_label.setStyleSheet(
                "color: #70d6a1; font-size: 22px; font-weight: bold;"
            )
            self.replay_detail_label.setText(
                "Capturando continuamente os últimos 30 segundos."
            )
            self.sidebar_status_label.setText("Em execução")

        else:
            self.replay_status_label.setText("Parado")
            self.replay_status_label.setStyleSheet(
                "color: #e5bc71; font-size: 22px; font-weight: bold;"
            )
            self.replay_detail_label.setText(
                "O Replay Buffer está pausado."
            )
            self.sidebar_status_label.setText("Buffer pausado")
            self.replay_toggle_button.setText("Iniciar Buffer")

        settings = load_audio_settings()
        microphone_name = settings.get(
            "microphone_name",
            "Padrão do Windows",
        )

        if running:
            self.audio_status_label.setText("Captura iniciada")
            self.audio_detail_label.setText(
                f"Entrada configurada: {microphone_name}. "
                "Consulte a seção Áudio para testar."
            )
        else:
            self.audio_status_label.setText("Buffer parado")
            self.audio_detail_label.setText(
                "A captura de áudio será retomada ao iniciar o Replay Buffer."
            )

        try:
            connected = bool(get_device_token())
        except Exception as error:
            print(f"[L DESKTOP] Erro ao verificar dispositivo: {error}")
            connected = False

        if connected:
            self.discord_status_label.setText("Conectado")
            self.discord_status_label.setStyleSheet(
                "color: #70d6a1; font-size: 22px; font-weight: bold;"
            )
            self.discord_detail_label.setText(
                "Dispositivo vinculado ao Discord."
            )
        else:
            self.discord_status_label.setText("Não vinculado")
            self.discord_status_label.setStyleSheet(
                "color: #e5bc71; font-size: 22px; font-weight: bold;"
            )
            self.discord_detail_label.setText(
                "Vincule o dispositivo para enviar arquivos."
            )

        self.queue_status_label.setText(str(self.pending_count))

        if self.pending_count:
            self.queue_detail_label.setText(
                "Arquivos aguardando envio ou confirmação."
            )
        else:
            self.queue_detail_label.setText(
                "Nenhum arquivo pendente."
            )

        if hasattr(self, "tray_replay_action"):
            self.tray_replay_action.setText(
                "Pausar Replay Buffer" if running
                else "Iniciar Replay Buffer"
            )

    def refresh_replay_history(self):
        if not hasattr(self, "replay_list"):
            return

        self.replay_list.clear()
        SAVED_DIR.mkdir(parents=True, exist_ok=True)

        files = sorted(
            SAVED_DIR.glob("replay_*.mp4"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

        for filepath in files[:100]:
            try:
                size_mb = filepath.stat().st_size / (1024 * 1024)

                modified = filepath.stat().st_mtime
                from datetime import datetime
                date_label = datetime.fromtimestamp(
                    modified
                ).strftime("%d/%m/%Y às %H:%M")

                item = QListWidgetItem(
                    f"{filepath.name}\n"
                    f"{date_label}  •  {size_mb:.2f} MiB"
                )

                item.setData(
                    Qt.ItemDataRole.UserRole,
                    str(filepath)
                )

                self.replay_list.addItem(item)

            except OSError as error:
                print(
                    f"[L DESKTOP] Erro ao listar {filepath.name}: {error}"
                )

        if files:
            latest = files[0]
            self.last_replay_label.setText(
                f"{latest.name}  •  "
                f"{latest.stat().st_size / (1024 * 1024):.2f} MiB"
            )
        else:
            self.last_replay_label.setText(
                "Nenhum replay salvo ainda."
            )

    def on_capture_queue_status(self, message):
        print(message)
        self.last_queue_message = message

    def on_capture_queue_pending_changed(self, count):
        self.pending_count = count

        if count:
            print(
                f"[L DESKTOP] Arquivos aguardando envio: {count}"
            )
        else:
            print("[L DESKTOP] Fila de envios vazia.")

    # ---------------------------------------------------------
    # WORKERS E ATALHOS
    # ---------------------------------------------------------

    def start_capture_queue(self):
        self.capture_queue_worker = CaptureQueueWorker(self)

        self.capture_queue_worker.status.connect(
            self.on_capture_queue_status
        )

        self.capture_queue_worker.pending_changed.connect(
            self.on_capture_queue_pending_changed
        )

        self.capture_queue_worker.start()

    def register_hotkeys(self):
        self.hotkey_id = keyboard.add_hotkey(
            "F8",
            self.capture_requested.emit,
        )

        self.replay_hotkey_id = keyboard.add_hotkey(
            "F9",
            self.replay_requested.emit,
        )

        print("[L DESKTOP] Atalho F8 registrado.")
        print("[L DESKTOP] Atalho F9 registrado.")

    def start_replay_buffer(self):
        try:
            self.recorder.start()
            print("[L DESKTOP] Replay Buffer iniciado automaticamente.")
        except Exception as error:
            print(f"[L DESKTOP] Erro ao iniciar Replay Buffer: {error}")
            traceback.print_exc()

    def start_update_checker(self):
        if not UPDATE_CHECK_ON_STARTUP:
            return

        self.update_worker = UpdateWorker(self)

        self.update_worker.update_available.connect(
            self.on_update_available
        )

        self.update_worker.check_failed.connect(
            self.on_update_check_failed
        )

        self.update_worker.start()

    # ---------------------------------------------------------
    # CAPTURAS E REPLAYS
    # ---------------------------------------------------------

    def capture_with_hotkey(self):
        self.capture_requested.emit()

    def start_capture(self):
        if self.capture_worker and self.capture_worker.isRunning():
            print("[L DESKTOP] Captura já está em andamento.")
            return

        self.capture_worker = CaptureWorker(self)

        self.capture_worker.completed.connect(
            self.on_capture_completed
        )

        self.capture_worker.start()

        print("[L DESKTOP] Captura iniciada em segundo plano.")

    def on_capture_completed(self, result):
        if isinstance(result, Exception):
            print(f"[L DESKTOP] Erro na captura: {result}")

        elif result:
            print("[L DESKTOP] Captura salva na fila de envio.")

        else:
            print("[L DESKTOP] Não foi possível salvar a captura.")

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

        self.refresh_runtime_status()

    def save_replay(self):
        try:
            print("[L DESKTOP] Preparando replay...")

            filepath = self.recorder.save_replay()

            print(f"[L DESKTOP] Replay salvo: {filepath}")
            self.last_replay_label.setText(filepath.name)

            if queue_replay(filepath):
                print("[L DESKTOP] Replay adicionado à fila de envio.")

            self.refresh_replay_history()
            self.refresh_runtime_status()

        except Exception as error:
            print(f"[L DESKTOP] Erro ao salvar replay: {error}")

            QMessageBox.warning(
                self,
                "Erro ao salvar replay",
                str(error),
            )

    # ---------------------------------------------------------
    # PASTAS E CONEXÃO
    # ---------------------------------------------------------

    def open_capture_folder(self):
        folder = DATA_DIR / "captures"
        folder.mkdir(parents=True, exist_ok=True)

        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(folder))
        )

    def open_replay_folder(self):
        SAVED_DIR.mkdir(parents=True, exist_ok=True)

        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(SAVED_DIR))
        )

    def open_data_folder(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(DATA_DIR))
        )

    def open_replay_item(self, item):
        filepath = item.data(Qt.ItemDataRole.UserRole)

        if not filepath:
            return

        QDesktopServices.openUrl(
            QUrl.fromLocalFile(filepath)
        )

    def open_link_window(self):
        window = LinkWindow(self)
        window.exec()
        self.refresh_runtime_status()

    # ---------------------------------------------------------
    # BANDEJA DO WINDOWS
    # ---------------------------------------------------------

    def setup_tray(self):
        self.tray = QSystemTrayIcon(self)

        self.tray.setToolTip("L Desktop")

        self.tray.setIcon(
            QApplication.style().standardIcon(
                QStyle.StandardPixmap.SP_ComputerIcon
            )
        )

        menu = QMenu(self)

        open_action = QAction("Abrir L Desktop", self)
        open_action.triggered.connect(self.show_main_window)

        capture_action = QAction("Capturar tela  (F8)", self)
        capture_action.triggered.connect(self.capture_with_hotkey)

        replay_action = QAction("Salvar replay  (F9)", self)
        replay_action.triggered.connect(self.save_replay)

        self.tray_replay_action = QAction(
            "Pausar Replay Buffer",
            self,
        )
        self.tray_replay_action.triggered.connect(
            self.toggle_replay
        )

        connection_action = QAction("Conexão Discord", self)
        connection_action.triggered.connect(self.open_link_window)

        exit_action = QAction("Encerrar L Desktop", self)
        exit_action.triggered.connect(QApplication.quit)

        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(capture_action)
        menu.addAction(replay_action)
        menu.addAction(self.tray_replay_action)
        menu.addSeparator()
        menu.addAction(connection_action)
        menu.addSeparator()
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_clicked)
        self.tray.show()

    def tray_clicked(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_main_window()

    def show_main_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # Mantém compatibilidade com chamadas anteriores.
    def show_panel(self):
        self.show_main_window()

    def closeEvent(self, event):
        # Fechar a janela apenas a esconde.
        # O aplicativo continua ativo na bandeja.
        event.ignore()
        self.hide()
        print("[L DESKTOP] Janela minimizada para a bandeja.")

    # ---------------------------------------------------------
    # ATUALIZAÇÕES
    # ---------------------------------------------------------

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
            QMessageBox.StandardButton.Yes,
        )

        if answer == QMessageBox.StandardButton.Yes:
            self.start_update_download(update)

    def start_update_download(self, update):
        self.update_progress = QProgressDialog(
            "Baixando atualização...",
            "Cancelar",
            0,
            100,
            self,
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
            self,
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
            f"Não foi possível baixar a atualização:\n\n{error}",
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
                updater_target,
            )

            QMessageBox.information(
                self,
                "Atualização pronta",
                "O L Desktop será encerrado para instalar a atualização.",
            )

            subprocess.Popen(
                [
                    str(updater_target),
                    "--parent-pid",
                    str(os.getpid()),
                    "--installer",
                    str(installer),
                    "--app-exe",
                    str(Path(sys.executable).resolve()),
                ],
                cwd=str(update_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS,
            )

            QApplication.quit()

        except Exception as error:
            QMessageBox.critical(
                self,
                "Erro ao iniciar atualização",
                str(error),
            )

    def on_update_check_failed(self, error):
        print(f"[UPDATE] Falha na verificação: {error}")

    # ---------------------------------------------------------
    # ENCERRAMENTO
    # ---------------------------------------------------------

    def cleanup(self):
        print("[L DESKTOP] Encerrando...")

        if hasattr(self, "status_timer"):
            self.status_timer.stop()

        try:
            if self.hotkey_id is not None:
                keyboard.remove_hotkey(self.hotkey_id)
        except Exception as error:
            print(f"[L DESKTOP] Erro ao remover F8: {error}")

        try:
            if self.replay_hotkey_id is not None:
                keyboard.remove_hotkey(self.replay_hotkey_id)
        except Exception as error:
            print(f"[L DESKTOP] Erro ao remover F9: {error}")

        try:
            if self.update_worker and self.update_worker.isRunning():
                self.update_worker.requestInterruption()
                self.update_worker.wait()
        except Exception as error:
            print(f"[L DESKTOP] Erro ao encerrar atualização: {error}")

        try:
            if self.download_worker and self.download_worker.isRunning():
                self.download_worker.requestInterruption()
                self.download_worker.wait()
        except Exception as error:
            print(f"[L DESKTOP] Erro ao encerrar download: {error}")

        try:
            if self.capture_worker and self.capture_worker.isRunning():
                print("[L DESKTOP] Aguardando captura terminar...")
                self.capture_worker.wait()
        except Exception as error:
            print(f"[L DESKTOP] Erro ao encerrar captura: {error}")

        try:
            if self.capture_queue_worker and self.capture_queue_worker.isRunning():
                print("[L DESKTOP] Encerrando fila de envios...")
                self.capture_queue_worker.stop()
                self.capture_queue_worker.wait()
        except Exception as error:
            print(f"[L DESKTOP] Erro ao encerrar fila: {error}")

        try:
            if (
                self.audio_test_worker
                and self.audio_test_worker.isRunning()
            ):
                self.audio_test_worker.wait()
        except Exception as error:
            print(f"[L DESKTOP] Erro ao encerrar teste de áudio: {error}")

        try:
            self.recorder.stop()
        except Exception as error:
            print(f"[L DESKTOP] Erro ao encerrar Replay Buffer: {error}")

        if hasattr(self, "tray"):
            self.tray.hide()

        print("[L DESKTOP] Encerrado.")


    def refresh_microphone_devices(self):
        settings = load_audio_settings()

        if self.microphone_combo.count():
            selected_id = self.microphone_combo.currentData()
            previous_name = self.microphone_names.get(selected_id)
        else:
            selected_id = settings.get("microphone_id")
            previous_name = settings.get("microphone_name")

        self.microphone_combo.clear()

        self.microphone_names = {
            None: "Padrão do Windows"
        }

        self.microphone_available_ids = set()

        try:
            default_info = get_default_microphone_info()
            default_label = (
                f"Padrão do Windows — {default_info['name']}"
            )
        except Exception:
            default_label = "Padrão do Windows"

        self.microphone_combo.addItem(default_label, None)

        try:
            devices = list_microphones()

            for device in devices:
                device_id = device["id"]
                device_name = device["name"]
                channels = device["channels"]

                label = (
                    f"{device_name} "
                    f"({channels} canais)"
                )

                self.microphone_combo.addItem(label, device_id)

                self.microphone_names[device_id] = device_name
                self.microphone_available_ids.add(device_id)

                print(
                    f"[AUDIO CONFIG] Encontrado: {device_name} "
                    f"[ID: {device_id}]"
                )

        except Exception as error:
            print(f"[AUDIO CONFIG] Erro ao listar microfones: {error}")

            self.audio_test_status.setText(
                f"Não foi possível listar os microfones: {error}"
            )

        # Preserva uma escolha salva mesmo quando o dispositivo
        # está temporariamente desconectado.
        if selected_id is not None:
            if selected_id not in self.microphone_available_ids:
                name = (
                    previous_name
                    or settings.get("microphone_name")
                    or "Dispositivo desconhecido"
                )

                self.microphone_combo.addItem(
                    f"Indisponível — {name}",
                    selected_id,
                )

                self.microphone_names[selected_id] = name

            index = self.microphone_combo.findData(selected_id)

            if index >= 0:
                self.microphone_combo.setCurrentIndex(index)

        self.audio_test_status.setText(
            f"{len(self.microphone_available_ids)} dispositivo(s) de entrada encontrado(s)."
        )


    def save_microphone_selection(self):
        microphone_id = self.microphone_combo.currentData()

        if (
            microphone_id is not None
            and microphone_id not in self.microphone_available_ids
        ):
            self.audio_test_status.setText(
                "O dispositivo selecionado não está disponível. "
                "Atualize a lista e escolha outro."
            )
            return False

        microphone_name = self.microphone_names.get(
            microphone_id,
            "Padrão do Windows",
        )

        try:
            save_audio_settings(
                microphone_id,
                microphone_name,
            )

            self.audio_test_status.setText(
                f"Preferência salva: {microphone_name}."
            )

            return True

        except Exception as error:
            self.audio_test_status.setText(
                f"Erro ao salvar preferência: {error}"
            )

            return False


    def apply_microphone_selection(self):
        if self.audio_test_worker and self.audio_test_worker.isRunning():
            self.audio_test_status.setText(
                "Aguarde o teste do microfone terminar."
            )
            return

        if not self.save_microphone_selection():
            return

        try:
            was_running = self.recorder.is_running()

            if was_running:
                print(
                    "[AUDIO CONFIG] Reiniciando Replay Buffer "
                    "para aplicar o microfone."
                )
                self.recorder.stop()

            self.recorder.start()

            self.audio_test_status.setText(
                "Microfone aplicado."
            )

            print("[AUDIO CONFIG] Configuração aplicada.")

            self.refresh_runtime_status()

        except Exception as error:
            print(
                f"[AUDIO CONFIG] Erro ao aplicar microfone: {error}"
            )

            self.audio_test_status.setText(
                f"Não foi possível aplicar a configuração: {error}"
            )

            QMessageBox.warning(
                self,
                "Erro ao aplicar configuração",
                str(error),
            )


    def test_selected_microphone(self):
        if self.audio_test_worker and self.audio_test_worker.isRunning():
            return

        microphone_id = self.microphone_combo.currentData()

        if (
            microphone_id is not None
            and microphone_id not in self.microphone_available_ids
        ):
            self.audio_test_status.setText(
                "O dispositivo não foi encontrado. Atualize a lista."
            )
            return

        self.audio_test_status.setText(
            "Testando por 2 segundos. Fale normalmente no microfone..."
        )

        self.microphone_test_button.setEnabled(False)

        self.audio_test_worker = AudioDeviceTestWorker(
            microphone_id,
            self,
        )

        self.audio_test_worker.completed.connect(
            self.on_audio_test_completed
        )

        self.audio_test_worker.start()


    def on_audio_test_completed(self, result):
        self.microphone_test_button.setEnabled(True)

        if "error" in result:
            message = result["error"]

            self.audio_test_status.setText(
                f"Falha ao abrir o microfone: {message}"
            )

            print(f"[AUDIO TEST] Falha: {message}")
            return

        peak = result["peak_dbfs"]
        rms = result["rms_dbfs"]

        if result["signal_detected"]:
            self.audio_test_status.setText(
                f"Sinal recebido de {result['device_name']}. "
                f"Pico: {peak:.1f} dBFS | RMS: {rms:.1f} dBFS."
            )
            print("[AUDIO TEST] Sinal de áudio detectado.")

        else:
            self.audio_test_status.setText(
                f"{result['device_name']} abriu e entregou amostras, "
                "mas o nível está muito baixo ou em silêncio. "
                "Confira se o microfone está ligado e fale durante o teste."
            )
            print(
                f"[AUDIO TEST] Pouco ou nenhum sinal. "
                f"Pico: {peak:.1f} dBFS | RMS: {rms:.1f} dBFS."
            )


def main():
    app = QApplication(sys.argv)

    app.setApplicationName("L Desktop")
    app.setQuitOnLastWindowClosed(False)

    window = LDesktop()
    window.show()

    QTimer.singleShot(2000, confirm_update_startup)

    app.aboutToQuit.connect(window.cleanup)

    signal.signal(
        signal.SIGINT,
        lambda *_: app.quit(),
    )

    signal_timer = QTimer()
    signal_timer.timeout.connect(lambda: None)
    signal_timer.start(200)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
