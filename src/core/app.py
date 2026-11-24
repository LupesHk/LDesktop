import sys
import signal
import os
import shutil
import ctypes
import subprocess
import traceback

from pathlib import Path
from ctypes import wintypes
from modules.live_viewer import LiveViewerDialog

import keyboard

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSize, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon

from core.paths import DATA_DIR, SAVED_DIR, ICON
from core.audio_config import (
    list_microphones,
    get_default_microphone_info,
    load_audio_settings,
    save_audio_settings,
    test_microphone,
    log_audio_error,
    AUDIO_LOG_FILE,
)

from modules.capture import (
    capture_screen,
    CaptureQueueWorker,
    queue_replay,
)
from modules.device import get_device_token
from modules.link_window import LinkWindow
from modules.live import LiveService
from modules.live_page import LivePage
from modules.live_publisher import LiveScreenPublisher

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSize, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon
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
    QListView,
    QListWidget,
    QListWidgetItem,
    QComboBox,
    QLineEdit,
    QCheckBox,
    QScrollArea,
)

from core.audio_config import (
    list_microphones,
    get_default_microphone_info,
    load_audio_settings,
    save_audio_settings,
    test_microphone,
    log_audio_error,
    AUDIO_LOG_FILE,
)

from replay.recorder import ReplayRecorder
from replay.game_profiles_dialog import GameProfilesDialog
from modules.capture import (
    capture_screen,
    CaptureQueueWorker,
    queue_replay,
)
from modules.link_window import LinkWindow
from modules.device import get_device_token

from core.update_config import APP_VERSION, UPDATE_CHECK_ON_STARTUP
from core.update_checker import UpdateWorker, UpdateDownloadWorker
from core.startup import (
    is_windows_startup_enabled,
    set_windows_startup,
    ensure_default_windows_startup,
)


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
            error_traceback = traceback.format_exc()

            log_audio_error(
                "Teste de microfone",
                error,
                error_traceback,
            )

            self.completed.emit({
                "error": str(error),
                "error_type": type(error).__name__,
                "traceback": error_traceback,
                "log_path": str(AUDIO_LOG_FILE),
            })

class ReplayCardFrame(QFrame):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class ReplayThumbnailWorker(QThread):

    def __init__(self, library, filepaths, parent=None):
        super().__init__(parent)
        self.library = library
        self.filepaths = list(filepaths)

    def run(self):
        for filepath in self.filepaths:
            if self.isInterruptionRequested():
                break

            try:
                self.library.ensure_thumbnail(filepath)
            except Exception as error:
                print(
                    f"[REPLAY LIBRARY] Erro na miniatura "
                    f"{filepath}: {error}"
                )


class LDesktop(QMainWindow):
    capture_requested = Signal()
    replay_requested = Signal()

    def __init__(self):
        super().__init__()

        self.setWindowTitle("L Desktop")
        self.setWindowIcon(QIcon(str(ICON)))
        self.resize(1080, 700)
        self.setMinimumSize(850, 580)
        self.live_viewer_dialog = None

        self.recorder = ReplayRecorder()

        self.capture_worker = None
        self.capture_queue_worker = None
        self.update_worker = None
        self.download_worker = None
        self.notified_update_versions = set()

        self.hotkey_id = None
        self.replay_hotkey_id = None

        self.pending_count = 0
        self.last_queue_message = "Fila de envios vazia."
        self._legacy_replays_imported = False
        self._thumbnail_backfill_started = False
        self.replay_selected_game = None
        self.replay_show_favorites = False
        self.thumbnail_worker = None

        self.capture_requested.connect(self.start_capture)
        self.replay_requested.connect(self.save_replay)
        self.audio_test_worker = None

        try:
            if ensure_default_windows_startup():
                print("[STARTUP] Inicializa??o com Windows ativada por padr?o.")
        except Exception as error:
            print(f"[STARTUP] N?o foi poss?vel configurar a inicializa??o autom?tica: {error}")

        self.setup_style()
        self.live_publisher = None
        self.setup_ui()
        self.setup_tray()
        self.live_friends = []

        self.live_service = LiveService(self)

        self.live_service.connection_changed.connect(
            self.on_live_connection_changed
        )

        self.live_service.friends_updated.connect(
            self.on_live_friends_updated
        )

        self.live_service.start()

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
                background-color: transparent;
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

        brand_icon = QLabel()
        brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_icon.setPixmap(
            QIcon(str(ICON)).pixmap(QSize(36, 36))
        )
        brand_mark_layout.addWidget(brand_icon)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)

        brand_title = QLabel("L Desktop")
        brand_title.setObjectName("brandTitle")

        brand_subtitle = QLabel("COMPANHIA NO WINDOWS")
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
            ("◉   Live", 2),
            ("⚙   Configurações", 3),
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
        self.page_stack.addWidget(self.build_live_page())
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
            "Organize, encontre e reviva seus melhores momentos."
        )

        workspace = QHBoxLayout()
        workspace.setContentsMargins(0, 2, 0, 0)
        workspace.setSpacing(14)

        # --------------------------------------------------
        # NAVEGACAO LATERAL
        # --------------------------------------------------
        sidebar = QFrame()
        sidebar.setObjectName("card")
        sidebar.setFixedWidth(190)

        sidebar.setStyleSheet("""
            QFrame#replaySidebar {
                background-color: #191925;
                border: 1px solid #2d2d40;
                border-radius: 12px;
            }
            QPushButton#replayNavButton {
                background-color: transparent;
                color: #aaa8bf;
                border: 1px solid transparent;
                border-radius: 7px;
                padding: 10px;
                text-align: left;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton#replayNavButton:hover {
                background-color: #252538;
                color: #ffffff;
            }
            QPushButton#replayNavButton:checked {
                background-color: #30284d;
                color: #d1c5ff;
                border: 1px solid #51417d;
                font-weight: bold;
            }
            QLabel#replaySidebarHeading {
                color: #77758f;
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
            }
        """)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 14)
        sidebar_layout.setSpacing(7)

        collections_heading = QLabel("COLECOES")
        collections_heading.setObjectName("replaySidebarHeading")

        sidebar_layout.addWidget(collections_heading)

        self.replay_all_button = QPushButton("Todos os replays")
        self.replay_all_button.setObjectName("replayNavButton")
        self.replay_all_button.setCheckable(True)
        self.replay_all_button.clicked.connect(
            lambda checked=False:
                self.select_replay_collection(None, False)
        )

        self.replay_favorites_button = QPushButton("Favoritos")
        self.replay_favorites_button.setObjectName("replayNavButton")
        self.replay_favorites_button.setCheckable(True)
        self.replay_favorites_button.clicked.connect(
            lambda checked=False:
                self.select_replay_collection(None, True)
        )

        sidebar_layout.addWidget(self.replay_all_button)
        sidebar_layout.addWidget(self.replay_favorites_button)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #303044;")
        sidebar_layout.addWidget(divider)

        games_heading = QLabel("JOGOS")
        games_heading.setObjectName("replaySidebarHeading")
        sidebar_layout.addWidget(games_heading)

        games_scroll = QScrollArea()
        games_scroll.setWidgetResizable(True)
        games_scroll.setFrameShape(QFrame.Shape.NoFrame)
        games_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        games_scroll.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea QWidget {
                background: transparent;
            }
        """)

        games_container = QWidget()
        self.replay_game_buttons_layout = QVBoxLayout(games_container)
        self.replay_game_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.replay_game_buttons_layout.setSpacing(5)
        self.replay_game_buttons_layout.addStretch()

        games_scroll.setWidget(games_container)
        sidebar_layout.addWidget(games_scroll, 1)

        sidebar_layout.addStretch()

        sidebar_note = QLabel(
            "Seus replays ficam salvos localmente."
        )
        sidebar_note.setObjectName("muted")
        sidebar_note.setWordWrap(True)
        sidebar_layout.addWidget(sidebar_note)

        workspace.addWidget(sidebar)

        # --------------------------------------------------
        # AREA PRINCIPAL
        # --------------------------------------------------
        main = QVBoxLayout()
        main.setSpacing(13)

        # Indicadores.
        stats = QHBoxLayout()
        stats.setSpacing(10)

        def create_stat(title, value, description):
            frame = QFrame()
            frame.setObjectName("card")
            frame.setMinimumHeight(82)

            box = QVBoxLayout(frame)
            box.setContentsMargins(14, 10, 14, 10)
            box.setSpacing(3)

            heading = QLabel(title)
            heading.setObjectName("cardTitle")

            number = QLabel(value)
            number.setObjectName("cardValue")

            detail = QLabel(description)
            detail.setObjectName("muted")

            box.addWidget(heading)
            box.addWidget(number)
            box.addWidget(detail)

            return frame, number

        stat, self.replay_stat_total = create_stat(
            "REPLAYS",
            "0",
            "Momentos salvos",
        )
        stats.addWidget(stat, 1)

        stat, self.replay_stat_games = create_stat(
            "JOGOS",
            "0",
            "Na sua biblioteca",
        )
        stats.addWidget(stat, 1)

        stat, self.replay_stat_storage = create_stat(
            "ARMAZENAMENTO",
            "0 MB",
            "Espaco utilizado",
        )
        stats.addWidget(stat, 1)

        main.addLayout(stats)

        # Cabecalho da galeria.
        section_header = QHBoxLayout()

        self.replay_section_title = QLabel("Todos os replays")
        self.replay_section_title.setStyleSheet("""
            QLabel {
                color: #f0edf9;
                font-size: 17px;
                font-weight: bold;
            }
        """)

        self.replay_result_label = QLabel("0 momentos")
        self.replay_result_label.setObjectName("muted")

        section_header.addWidget(self.replay_section_title)
        section_header.addStretch()
        section_header.addWidget(self.replay_result_label)

        main.addLayout(section_header)

        # Pesquisa e filtros.
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.replay_search = QLineEdit()
        self.replay_search.setPlaceholderText(
            "Pesquisar jogos e replays..."
        )
        self.replay_search.setClearButtonEnabled(True)
        self.replay_search.setMinimumHeight(40)
        self.replay_search.setStyleSheet("""
            QLineEdit {
                background-color: #191925;
                color: #efedf8;
                border: 1px solid #34344b;
                border-radius: 8px;
                padding: 9px 12px;
                selection-background-color: #7657e8;
            }
            QLineEdit:focus {
                border: 1px solid #7657e8;
            }
            QLineEdit::placeholder {
                color: #77758f;
            }
        """)

        self.replay_period_filter = QComboBox()
        self.replay_period_filter.setMinimumWidth(135)
        self.replay_period_filter.setMinimumHeight(40)
        self.replay_period_filter.addItem("Todo o periodo", "all")
        self.replay_period_filter.addItem("Hoje", "today")
        self.replay_period_filter.addItem("Ultimos 7 dias", "7days")
        self.replay_period_filter.addItem("Este mes", "month")

        self.replay_sort_filter = QComboBox()
        self.replay_sort_filter.setMinimumWidth(150)
        self.replay_sort_filter.setMinimumHeight(40)
        self.replay_sort_filter.addItem("Mais recentes", "newest")
        self.replay_sort_filter.addItem("Mais antigos", "oldest")
        self.replay_sort_filter.addItem("Maior tamanho", "largest")
        self.replay_sort_filter.addItem("Menor tamanho", "smallest")

        combo_style = """
            QComboBox {
                background-color: #191925;
                color: #e8e5f4;
                border: 1px solid #34344b;
                border-radius: 8px;
                padding: 8px 10px;
            }
            QComboBox:hover {
                border-color: #62528e;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #191925;
                color: #e8e5f4;
                selection-background-color: #30284d;
                border: 1px solid #34344b;
                outline: none;
            }
        """

        self.replay_period_filter.setStyleSheet(combo_style)
        self.replay_sort_filter.setStyleSheet(combo_style)

        refresh_button = QPushButton("Atualizar")
        refresh_button.setMinimumHeight(40)
        refresh_button.clicked.connect(self.refresh_replay_history)

        folder_button = QPushButton("Abrir pasta")
        folder_button.setMinimumHeight(40)
        folder_button.clicked.connect(self.open_replay_folder)

        toolbar.addWidget(self.replay_search, 1)
        toolbar.addWidget(self.replay_period_filter)
        toolbar.addWidget(self.replay_sort_filter)
        toolbar.addWidget(refresh_button)
        toolbar.addWidget(folder_button)

        main.addLayout(toolbar)

        # Galeria.
        self.replay_list = QListWidget()
        self.replay_list.setObjectName("replayGallery")
        self.replay_list.setViewMode(QListView.ViewMode.IconMode)
        self.replay_list.setFlow(QListView.Flow.LeftToRight)
        self.replay_list.setWrapping(True)
        self.replay_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.replay_list.setMovement(QListView.Movement.Static)
        self.replay_list.setIconSize(QSize(220, 124))
        self.replay_list.setGridSize(QSize(258, 230))
        self.replay_list.setSpacing(12)
        self.replay_list.setWordWrap(True)
        self.replay_list.setUniformItemSizes(True)
        self.replay_list.setTextElideMode(
            Qt.TextElideMode.ElideRight
        )
        self.replay_list.setStyleSheet("""
            QListWidget#replayGallery {
                background-color: #13131e;
                border: 1px solid #29293c;
                border-radius: 11px;
                padding: 10px;
                outline: none;
            }
            QListWidget#replayGallery::item {
                background: transparent;
                border: none;
                padding: 0px;
            }
            QListWidget#replayGallery::item:selected {
                background: transparent;
            }
        """)

        self.replay_list.itemDoubleClicked.connect(
            self.open_replay_item
        )

        main.addWidget(self.replay_list, 1)

        self.replay_empty_label = QLabel(
            "Nenhum replay encontrado.\n"
            "Salve um momento com F9 para ele aparecer aqui."
        )
        self.replay_empty_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.replay_empty_label.setObjectName("muted")
        self.replay_empty_label.hide()

        main.addWidget(self.replay_empty_label)

        workspace.addLayout(main, 1)
        layout.addLayout(workspace, 1)

        self.replay_search.textChanged.connect(
            self.refresh_replay_history
        )
        self.replay_period_filter.currentIndexChanged.connect(
            self.refresh_replay_history
        )
        self.replay_sort_filter.currentIndexChanged.connect(
            self.refresh_replay_history
        )

        return page

    def select_replay_collection(self, game_name=None, favorites=False):
        self.replay_selected_game = game_name
        self.replay_show_favorites = favorites
        self.refresh_replay_history()

    def refresh_replay_sidebar(self, games, summary):
        self.replay_all_button.setChecked(
            self.replay_selected_game is None
            and not self.replay_show_favorites
        )

        self.replay_favorites_button.setChecked(
            self.replay_show_favorites
        )

        self.replay_all_button.setText(
            f"Todos os replays    {summary['replay_count']}"
        )

        favorites_count = sum(
            1 for record in self.recorder.library.list_replays(limit=10000)
            if record.get("is_favorite")
        )

        self.replay_favorites_button.setText(
            f"Favoritos    {favorites_count}"
        )

        while self.replay_game_buttons_layout.count():
            item = self.replay_game_buttons_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        for game in games:
            name = game["game_name"]
            count = game["replay_count"]

            button = QPushButton(f"{name}    {count}")
            button.setObjectName("replayNavButton")
            button.setCheckable(True)
            button.setChecked(
                self.replay_selected_game == name
                and not self.replay_show_favorites
            )

            button.clicked.connect(
                lambda checked=False, selected=name:
                    self.select_replay_collection(selected, False)
            )

            self.replay_game_buttons_layout.addWidget(button)

        self.replay_game_buttons_layout.addStretch()

    def build_live_page(self):

        page, layout = self.page_container(
            "Live",
            "Encontre os membros do servidor e acompanhe "
            "quem está disponível no L Desktop."
        )

        self.live_page = LivePage()

        self.live_page.share_button.clicked.connect(
            self.toggle_live_sharing
        )

        self.live_page.watch_requested.connect(
            self.open_live_viewer
        )

        layout.addWidget(self.live_page, 1)

        return page

    def build_settings_page(self):
        page, layout = self.page_container(
            "Configurações",
            "Personalize o funcionamento do L Desktop."
        )

        # ÁUDIO
        # CONFIGURA??ES COM ROLAGEM VERTICAL
        scroll_area = QScrollArea()
        scroll_area.setObjectName("settingsScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.viewport().setObjectName("settingsScrollViewport")
        scroll_area.setStyleSheet("""
            QScrollArea#settingsScrollArea {
                background-color: #11111a;
                border: none;
            }
            QWidget#settingsScrollViewport {
                background-color: #11111a;
            }
            QWidget#settingsScrollContent {
                background-color: #11111a;
            }
        """)
        scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        content = QWidget()
        content.setObjectName("settingsScrollContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(17)

        scroll_area.setWidget(content)
        layout.addWidget(scroll_area, 1)
        layout = content_layout

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

        startup_card = QFrame()
        startup_card.setObjectName("card")

        startup_layout = QVBoxLayout(startup_card)
        startup_layout.setContentsMargins(18, 17, 18, 17)
        startup_layout.setSpacing(9)

        startup_title = QLabel("INICIALIZAÇÃO DO WINDOWS")
        startup_title.setObjectName("cardTitle")

        self.startup_checkbox = QCheckBox(
            "Iniciar L Desktop com o Windows"
        )
        self.startup_checkbox.setChecked(
            is_windows_startup_enabled()
        )
        self.startup_checkbox.toggled.connect(
            self.on_startup_toggled
        )

        startup_description = QLabel(
            "O aplicativo iniciará em segundo plano, "
            "disponível na bandeja do Windows."
        )
        startup_description.setObjectName("muted")
        startup_description.setWordWrap(True)

        startup_layout.addWidget(startup_title)
        startup_layout.addWidget(self.startup_checkbox)
        startup_layout.addWidget(startup_description)

        layout.addWidget(startup_card)

        self.refresh_microphone_devices()

        # JOGOS E IDENTIFICACAO
        games_card = QFrame()
        games_card.setObjectName("card")

        games_layout = QVBoxLayout(games_card)
        games_layout.setContentsMargins(18, 17, 18, 17)
        games_layout.setSpacing(9)

        games_title = QLabel("JOGOS E IDENTIFICACAO")
        games_title.setObjectName("cardTitle")

        games_description = QLabel(
            "Cadastre jogos, configure executaveis e "
            "personalize o reconhecimento automatico."
        )
        games_description.setObjectName("muted")
        games_description.setWordWrap(True)

        games_button = QPushButton("Gerenciar jogos")
        games_button.setObjectName("primaryButton")
        games_button.clicked.connect(self.open_game_profiles)

        games_layout.addWidget(games_title)
        games_layout.addWidget(games_description)
        games_layout.addWidget(games_button)

        layout.addWidget(games_card)

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
            "Live",
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

    def set_replay_favorite(self, filepath, favorite):
        try:
            self.recorder.library.set_favorite(filepath, favorite)
            self.refresh_replay_history()

            print(
                f"[REPLAY LIBRARY] Favorito atualizado: "
                f"{Path(filepath).name} -> {favorite}"
            )

        except Exception as error:
            QMessageBox.warning(
                self,
                "Favoritos",
                str(error),
            )

    def delete_replay_from_library(self, filepath):
        answer = QMessageBox.question(
            self,
            "Excluir replay",
            (
                "Deseja excluir permanentemente este replay?\\n\\n"
                f"{Path(filepath).name}\\n\\n"
                "O arquivo original e sua miniatura serao removidos. "
                "Essa acao nao pode ser desfeita."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.recorder.library.delete_replay(filepath)
            self.refresh_replay_history()
            print("[REPLAY LIBRARY] Replay excluido.")

        except Exception as error:
            QMessageBox.warning(
                self,
                "Erro ao excluir replay",
                str(error),
            )

    def show_replay_context_menu(
        self,
        filepath,
        is_favorite,
        global_position,
    ):
        menu = QMenu(self)

        favorite_action = menu.addAction(
            "Desfavoritar" if is_favorite else "Favoritar"
        )

        menu.addSeparator()
        delete_action = menu.addAction("Excluir")

        selected = menu.exec(global_position)

        if selected == favorite_action:
            self.set_replay_favorite(
                filepath,
                not is_favorite,
            )

        elif selected == delete_action:
            self.delete_replay_from_library(filepath)

    def create_replay_card(
        self,
        filepath,
        game_name,
        date_label,
        size_mb,
        thumbnail,
        is_favorite,
    ):
        card = ReplayCardFrame(self)
        card.setObjectName("replayCard")
        card.setFixedSize(238, 205)
        card.setToolTip(str(filepath))
        card.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )

        card.customContextMenuRequested.connect(
            lambda point, widget=card,
                   item_path=str(filepath), favorite=is_favorite:
                self.show_replay_context_menu(
                    item_path,
                    favorite,
                    widget.mapToGlobal(point),
                )
        )

        card.setStyleSheet("""
            QFrame#replayCard {
                background-color: #191925;
                border: 1px solid #303044;
                border-radius: 10px;
            }
            QFrame#replayCard:hover {
                border: 1px solid #7657e8;
                background-color: #20202f;
            }
            QLabel#replayGameLabel {
                color: #e7e2fa;
                font-size: 12px;
                font-weight: bold;
                background: transparent;
                border: none;
            }
            QLabel#replayMetadataLabel {
                color: #9291a8;
                font-size: 10px;
                background: transparent;
                border: none;
            }
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        preview_container = QWidget(card)
        preview_layout = QGridLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        preview = QLabel()
        preview.setFixedSize(220, 124)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setStyleSheet("""
            QLabel {
                background-color: #101018;
                color: #9291a8;
                border-radius: 7px;
                border: none;
            }
        """)
        preview.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )

        if thumbnail and Path(thumbnail).is_file():
            preview_icon = QIcon(str(thumbnail))
            pixmap = preview_icon.pixmap(QSize(220, 124))

            if not pixmap.isNull():
                preview.setPixmap(pixmap)
            else:
                preview.setText("Previa indisponivel")
        else:
            preview.setText("Previa indisponivel")

        preview_layout.addWidget(preview, 0, 0)

        preview_container.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )

        preview_container.customContextMenuRequested.connect(
            lambda point, widget=preview_container,
                   item_path=str(filepath), favorite=is_favorite:
                self.show_replay_context_menu(
                    item_path,
                    favorite,
                    widget.mapToGlobal(point),
                )
        )

        layout.addWidget(
            preview_container,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        game_label = QLabel(game_name)
        game_label.setObjectName("replayGameLabel")
        game_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )

        metadata_label = QLabel(
            f"{date_label}\n{size_mb:.2f} MiB"
        )
        metadata_label.setObjectName("replayMetadataLabel")
        metadata_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )

        layout.addWidget(game_label)
        layout.addWidget(metadata_label)

        return card

    def refresh_replay_history(self):
        if not hasattr(self, "replay_list"):
            return

        self.replay_list.clear()

        try:
            library = self.recorder.library

            if not self._legacy_replays_imported:
                imported = library.import_legacy_replays()
                self._legacy_replays_imported = True

                if imported:
                    print(
                        f"[REPLAY LIBRARY] "
                        f"{imported} replay(s) antigo(s) catalogado(s)."
                    )

            all_records = library.list_replays(limit=10000)
            games = library.list_games()
            summary = library.get_summary()

        except Exception as error:
            print(
                f"[REPLAY LIBRARY] Erro ao consultar catalogo: {error}"
            )
            return

        self.replay_stat_total.setText(
            str(summary["replay_count"])
        )

        self.replay_stat_games.setText(
            str(summary["game_count"])
        )

        total_bytes = summary["total_bytes"]

        if total_bytes >= 1024 ** 3:
            storage_label = f"{total_bytes / (1024 ** 3):.2f} GB"
        elif total_bytes >= 1024 ** 2:
            storage_label = f"{total_bytes / (1024 ** 2):.1f} MB"
        else:
            storage_label = f"{total_bytes / 1024:.0f} KB"

        self.replay_stat_storage.setText(storage_label)

        self.refresh_replay_sidebar(games, summary)

        from datetime import datetime, timedelta

        search = self.replay_search.text().strip().casefold()
        selected_game = self.replay_selected_game
        favorites_only = self.replay_show_favorites
        period = self.replay_period_filter.currentData()
        sort_mode = self.replay_sort_filter.currentData()

        now = datetime.now()
        today = now.date()
        week_start = now - timedelta(days=7)

        records = []

        for record in all_records:
            try:
                filepath = Path(record["file_path"])

                if not filepath.is_file():
                    continue

                if selected_game and record["game_name"] != selected_game:
                    continue

                if favorites_only and not record.get("is_favorite"):
                    continue

                captured = datetime.fromtimestamp(
                    record["captured_at"]
                )

                if period == "today" and captured.date() != today:
                    continue

                if period == "7days" and captured < week_start:
                    continue

                if (
                    period == "month"
                    and (captured.year, captured.month)
                    != (now.year, now.month)
                ):
                    continue

                searchable = " ".join((
                    record.get("title") or "",
                    record.get("file_name") or "",
                    record.get("game_name") or "",
                )).casefold()

                if search and search not in searchable:
                    continue

                records.append(record)

            except (OSError, KeyError, TypeError, ValueError) as error:
                print(
                    f"[REPLAY LIBRARY] Registro ignorado: {error}"
                )

        if sort_mode == "oldest":
            records.sort(key=lambda item: item["captured_at"])
        elif sort_mode == "largest":
            records.sort(
                key=lambda item: item.get("file_size_bytes", 0),
                reverse=True,
            )
        elif sort_mode == "smallest":
            records.sort(
                key=lambda item: item.get("file_size_bytes", 0),
            )
        else:
            records.sort(
                key=lambda item: item["captured_at"],
                reverse=True,
            )

        if favorites_only:
            section_title = "Seus favoritos"
        elif selected_game:
            section_title = selected_game
        else:
            section_title = "Todos os replays"

        if period != "all":
            period_labels = {
                "today": "Hoje",
                "7days": "Ultimos 7 dias",
                "month": "Este mes",
            }
            section_title += f"  /  {period_labels.get(period, '')}"

        self.replay_section_title.setText(section_title)

        visible_replays = []

        for record in records:
            try:
                filepath = Path(record["file_path"])
                metadata = filepath.stat()

                size_mb = metadata.st_size / (1024 * 1024)

                date_label = datetime.fromtimestamp(
                    record["captured_at"]
                ).strftime("%d/%m/%Y  %H:%M")

                thumbnail_value = record.get("thumbnail_path")
                thumbnail = (
                    Path(thumbnail_value)
                    if thumbnail_value
                    else None
                )

                if thumbnail and not thumbnail.is_file():
                    thumbnail = None

                is_favorite = bool(record.get("is_favorite"))

                item = QListWidgetItem()
                item.setSizeHint(QSize(258, 230))

                item.setData(
                    Qt.ItemDataRole.UserRole,
                    str(filepath),
                )

                item.setData(
                    Qt.ItemDataRole.UserRole + 1,
                    is_favorite,
                )

                self.replay_list.addItem(item)

                card = self.create_replay_card(
                    filepath=filepath,
                    game_name=record["game_name"],
                    date_label=date_label,
                    size_mb=size_mb,
                    thumbnail=thumbnail,
                    is_favorite=is_favorite,
                )

                card.doubleClicked.connect(
                    lambda item_path=str(filepath):
                        self.open_replay_path(item_path)
                )

                self.replay_list.setItemWidget(item, card)
                visible_replays.append((filepath, metadata))

            except (OSError, KeyError, TypeError, ValueError) as error:
                print(
                    f"[REPLAY LIBRARY] Erro ao montar card: {error}"
                )

        count = len(visible_replays)
        self.replay_result_label.setText(
            f"{count} momento(s)"
        )

        self.replay_list.setVisible(count > 0)
        self.replay_empty_label.setVisible(count == 0)

        if count == 0:
            if search or selected_game or favorites_only or period != "all":
                self.replay_empty_label.setText(
                    "Nenhum replay corresponde aos filtros selecionados."
                )
            else:
                self.replay_empty_label.setText(
                    "Sua biblioteca ainda esta vazia.\n"
                    "Salve um momento com F9 para ele aparecer aqui."
                )

        if visible_replays:
            latest, metadata = visible_replays[0]
            self.last_replay_label.setText(
                f"{latest.name}  |  "
                f"{metadata.st_size / (1024 * 1024):.2f} MiB"
            )
        else:
            self.last_replay_label.setText(
                "Nenhum replay salvo ainda."
            )

        # Gera algumas miniaturas antigas em segundo plano.
        if not self._thumbnail_backfill_started:
            missing = []

            for record in all_records:
                thumbnail_value = record.get("thumbnail_path")
                thumbnail = (
                    Path(thumbnail_value)
                    if thumbnail_value
                    else None
                )

                if not thumbnail or not thumbnail.is_file():
                    filepath = Path(record["file_path"])

                    if filepath.is_file():
                        missing.append(filepath)

                if len(missing) >= 5:
                    break

            if missing:
                self._thumbnail_backfill_started = True

                self.thumbnail_worker = ReplayThumbnailWorker(
                    library,
                    missing,
                    self,
                )

                self.thumbnail_worker.finished.connect(
                    self.refresh_replay_history
                )

                self.thumbnail_worker.start()

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
    # LIVE

    def open_live_viewer(self, user_id, display_name):
        if (
            self.live_viewer_dialog
            and self.live_viewer_dialog.isVisible()
        ):
            self.live_viewer_dialog.raise_()
            self.live_viewer_dialog.activateWindow()
            return

        self.live_viewer_dialog = LiveViewerDialog(
            user_id,
            display_name,
            self,
        )

        self.live_viewer_dialog.show()

    def toggle_live_sharing(self):

        if self.live_publisher and self.live_publisher.isRunning():

            self.live_page.set_stream_state(
                "stopping",
                "Encerrando transmissão..."
            )

            self.live_publisher.stop()
            return

        publisher = LiveScreenPublisher(self)

        self.live_publisher = publisher

        publisher.state_changed.connect(
            self.on_live_publisher_state_changed
        )

        publisher.finished.connect(
            self.on_live_publisher_finished
        )

        self.live_page.set_stream_state(
            "connecting",
            "Conectando ao LiveKit..."
        )

        publisher.start()


    def on_live_publisher_state_changed(self, state, message):

        print(f"[LIVE STREAM] {state}: {message}")

        if hasattr(self, "live_page"):
            self.live_page.set_stream_state(
                state,
                message
            )


    def on_live_publisher_finished(self):

        publisher = self.live_publisher

        if publisher:
            self.live_publisher = None
            publisher.deleteLater()

    def on_live_connection_changed(self, online, message):

        state = "Conectado" if online else "Desconectado"

        print(f"[LIVE] {state}: {message}")

        if hasattr(self, "live_page"):
            self.live_page.set_connection_status(
                online,
                message,
            )

    def on_live_friends_updated(self, friends):

        self.live_friends = friends

        if hasattr(self, "live_page"):
            self.live_page.set_friends(friends)

        online_count = sum(
            1 for friend in friends
            if friend.get("liveOnline")
        )

        print(
            f"[LIVE] Lista atualizada: "
            f"{len(friends)} membros, "
            f"{online_count} com L Desktop ativo."
        )

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

    def on_startup_toggled(self, enabled):
        try:
            set_windows_startup(enabled)

            state = "ativada" if enabled else "desativada"
            print(
                f"[STARTUP] Inicializa??o com Windows {state}."
            )

        except Exception as error:
            print(f"[STARTUP] Erro ao alterar configura??o: {error}")

            self.startup_checkbox.blockSignals(True)
            self.startup_checkbox.setChecked(not enabled)
            self.startup_checkbox.blockSignals(False)

            QMessageBox.warning(
                self,
                "Inicializa??o do Windows",
                f"N?o foi poss?vel alterar a configura??o:\n\n{error}",
            )

    def start_update_checker(self):
        if not UPDATE_CHECK_ON_STARTUP:
            return

        # Consulta imediata e repeti??o a cada 15 minutos.
        if not hasattr(self, "update_check_timer"):
            self.update_check_timer = QTimer(self)
            self.update_check_timer.setInterval(15 * 60 * 1000)
            self.update_check_timer.timeout.connect(
                self.start_update_checker
            )
            self.update_check_timer.start()

        # Evita consultas simult?neas.
        if self.update_worker and self.update_worker.isRunning():
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

    def open_replay_path(self, filepath):
        filepath = Path(filepath)

        if not filepath.is_file():
            QMessageBox.warning(
                self,
                "Replay nao encontrado",
                str(filepath),
            )
            return

        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(filepath))
        )

    def open_replay_item(self, item):
        filepath = item.data(Qt.ItemDataRole.UserRole)

        if filepath:
            self.open_replay_path(filepath)

    def open_game_profiles(self):
        dialog = GameProfilesDialog(
            self.recorder.game_detector,
            self,
        )
        dialog.exec()

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

        self.tray.setIcon(QIcon(str(ICON)))

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
        version = getattr(update, "version", None)

        # N?o repetir o aviso da mesma vers?o nesta sess?o.
        if version and version in self.notified_update_versions:
            return

        if version:
            self.notified_update_versions.add(version)

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

        try:
            if self.live_publisher and self.live_publisher.isRunning():

                print("[LIVE STREAM] Encerrando transmissão...")

                self.live_publisher.stop()
                self.live_publisher.wait(15000)
            if (
                self.live_viewer_dialog
                and self.live_viewer_dialog.isVisible()
            ):
                self.live_viewer_dialog.close()

        except Exception as error:
            print(f"[LIVE STREAM] Erro no encerramento: {error}")

        try:
            if hasattr(self, "live_service"):
                if self.live_service.isRunning():
                    print("[LIVE] Encerrando serviço...")

                    self.live_service.stop()

                    if not self.live_service.wait(15000):
                        print("[LIVE] Aguardando finalização do serviço...")
                        self.live_service.wait()

        except Exception as error:
            print(f"[LIVE] Erro ao encerrar serviço: {error}")

        if hasattr(self, "update_check_timer"):
            self.update_check_timer.stop()

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

        if not previous_name:
            previous_name = settings.get("microphone_name")

        self.microphone_combo.clear()

        self.microphone_names = {
            None: "Padrão do Windows"
        }

        self.microphone_available_ids = set()

        try:
            default_info = get_default_microphone_info()
            default_label = (
                f"Padrão do Windows — "
                f"{default_info['name']} "
                f"({default_info['hostapi']})"
            )
        except Exception:
            default_label = "Padrão do Windows"

        self.microphone_combo.addItem(default_label, None)

        try:
            devices = list_microphones()

            for device in devices:
                device_id = device["id"]
                device_name = device["name"]
                hostapi = device["hostapi"]
                channels = device["channels"]
                samplerate = device["samplerate"]

                label = (
                    f"{device_name} — {hostapi} "
                    f"({samplerate / 1000:g} kHz, "
                    f"{channels} canais)"
                )

                self.microphone_combo.addItem(label, device_id)

                self.microphone_names[device_id] = device_name
                self.microphone_available_ids.add(device_id)

                print(
                    f"[AUDIO CONFIG] Encontrado: {device_name} "
                    f"[API: {hostapi}, ID: {device_id}]"
                )

        except Exception as error:
            print(f"[AUDIO CONFIG] Erro ao listar microfones: {error}")

            self.audio_test_status.setText(
                f"Não foi possível listar os microfones: {error}"
            )

        # Migra automaticamente IDs antigos do SoundCard.
        if (
            selected_id is not None
            and selected_id not in self.microphone_available_ids
            and previous_name
        ):
            candidates = [
                device
                for device in devices
                if device["name"].casefold() == previous_name.casefold()
            ] if "devices" in locals() else []

            if candidates:
                candidates.sort(
                    key=lambda device: (
                        0 if device["hostapi"] == "Windows WASAPI" else 1
                    )
                )

                selected_id = candidates[0]["id"]

                print(
                    f"[AUDIO CONFIG] ID antigo migrado para: "
                    f"{selected_id}"
                )

        # Preserva seleção, inclusive quando o dispositivo está ausente.
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
            f"{len(self.microphone_available_ids)} "
            f"dispositivo(s) de entrada encontrado(s)."
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
            error_type = result.get("error_type", "Erro")
            message = result["error"]

            error_summary = f"{error_type}: {message}"

            self.audio_test_status.setText(
                f"Falha ao abrir o microfone: {error_summary}"
            )

            print(f"[AUDIO TEST] {error_summary}")

            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Critical)
            dialog.setWindowTitle("Falha no teste do microfone")
            dialog.setText(error_summary)

            dialog.setInformativeText(
                f"O diagnóstico completo foi salvo em:\n"
                f"{result.get('log_path', AUDIO_LOG_FILE)}"
            )

            dialog.setDetailedText(
                result.get("traceback", "Detalhes indisponíveis.")
            )

            dialog.exec()
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
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "LupesHk.LDesktop.1.0"
            )
        except Exception as error:
            print(f"[L DESKTOP] Aviso: AppUserModelID não definido: {error}")

    app = QApplication(sys.argv)

    app.setApplicationName("L Desktop")
    app.setWindowIcon(QIcon(str(ICON)))
    app.setQuitOnLastWindowClosed(False)

    window = LDesktop()

    if "--background" in sys.argv[1:]:
        print("[L DESKTOP] Iniciado em segundo plano na bandeja.")
    else:
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