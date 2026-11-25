from PySide6.QtCore import Qt, QSize, QUrl, Signal, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QPixmap

from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkRequest,
    QNetworkReply,
)
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QPushButton,
    QComboBox,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
)

from core.live_settings import (
    load_live_settings,
    save_live_settings,
)
from modules.live_capture import list_capture_windows, list_capture_monitors


class LiveFriendCard(QFrame):
    watch_requested = Signal(str, str)
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("liveFriendCard")
        self.avatar_url = ""

        self.setStyleSheet('\n    QFrame#liveFriendCard {\n        background-color: #191923;\n        border: 1px solid #303047;\n        border-radius: 13px;\n    }\n\n    QFrame#liveFriendCard:hover {\n        border-color: #62528E;\n        background-color: #1D1C2A;\n    }\n\n    QLabel#liveFriendName {\n        color: #F0EDF9;\n        font-size: 13px;\n        font-weight: bold;\n    }\n\n    QLabel#liveFriendUsername {\n        color: #9997AD;\n        font-size: 11px;\n    }\n\n    QLabel#liveFriendDiscord {\n        color: #9290A7;\n        font-size: 10px;\n    }\n\n    QLabel#liveFriendStatus {\n        font-size: 11px;\n        font-weight: bold;\n    }\n')

        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 12, 13, 12)
        layout.setSpacing(13)

        self.avatar = QLabel()
        self.avatar.setFixedSize(46, 46)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.avatar.setStyleSheet('\n    QLabel {\n        background-color: #30284D;\n        color: #D7CDFF;\n        border: 1px solid #51417D;\n        border-radius: 23px;\n        font-size: 14px;\n        font-weight: bold;\n    }\n')

        layout.addWidget(self.avatar)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)

        self.name_label = QLabel("Membro")
        self.name_label.setObjectName("liveFriendName")

        self.username_label = QLabel("")
        self.username_label.setObjectName("liveFriendUsername")

        self.discord_label = QLabel("Discord: offline")
        self.discord_label.setObjectName("liveFriendDiscord")

        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.username_label)
        info_layout.addWidget(self.discord_label)

        layout.addLayout(info_layout, 1)

        self.status_label = QLabel("L Desktop fechado")
        self.status_label.setObjectName("liveFriendStatus")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight |
            Qt.AlignmentFlag.AlignVCenter
        )

        layout.addWidget(self.status_label)

        self.user_id = None

        self.watch_button = QPushButton("Assistir")
        self.watch_button.setFixedWidth(90)
        self.watch_button.setEnabled(False)

        self.watch_button.setStyleSheet('\n    QPushButton {\n        background-color: #2D2548;\n        color: #D7CDFF;\n        border: 1px solid #51417D;\n        border-radius: 8px;\n        padding: 8px 12px;\n        font-weight: bold;\n    }\n\n    QPushButton:hover {\n        background-color: #403363;\n        border-color: #8065E8;\n    }\n\n    QPushButton:disabled {\n        color: #77758A;\n        background-color: #20202E;\n        border-color: #303047;\n    }\n')

        self.watch_button.clicked.connect(
            self.request_watch
        )

        layout.addWidget(self.watch_button)

    def request_watch(self):
        if self.user_id:
            self.watch_requested.emit(
                self.user_id,
                self.name_label.text(),
            )
    def update_friend(self, friend):

        name = friend.get("displayName") or friend.get("username") or "Membro"
        username = friend.get("username") or ""

        discord_status = friend.get("discordStatus", "offline")
        live_online = bool(friend.get("liveOnline", False))
        live_streaming = bool(friend.get("liveStreaming", False))
        self.user_id = friend.get("id")
        self.watch_button.setEnabled(live_streaming)

        self.name_label.setText(name)
        self.username_label.setText(
            f"@{username}" if username else ""
        )

        discord_labels = {
            "online": "Online",
            "idle": "Ausente",
            "dnd": "Não perturbe",
            "offline": "Offline",
        }

        self.discord_label.setText(
            f"Discord: {discord_labels.get(discord_status, discord_status)}"
        )

        if live_online:
            self.status_label.setText("Online")
            self.status_label.setStyleSheet(
                'color: #70D9A5;'
            )
        else:
            self.status_label.setText("Offline")
            self.status_label.setStyleSheet(
                'color: #9997AD;'
            )

        avatar_url = friend.get("avatar") or ""

        if avatar_url != self.avatar_url:
            self.avatar_url = avatar_url
            self.set_fallback_avatar(name)

        return avatar_url

    def set_fallback_avatar(self, name):

        parts = name.split()

        initials = "".join(
            part[0] for part in parts[:2]
        ).upper()

        self.avatar.setPixmap(QPixmap())
        self.avatar.setText(initials or "?")

    def set_avatar_pixmap(self, pixmap):

        size = 46

        scaled = pixmap.scaled(
            QSize(size, size),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

        left = (scaled.width() - size) // 2
        top = (scaled.height() - size) // 2

        cropped = scaled.copy(left, top, size, size)

        rounded = QPixmap(size, size)
        rounded.fill(Qt.GlobalColor.transparent)

        painter = QPainter(rounded)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        path = QPainterPath()
        path.addEllipse(0, 0, size, size)

        painter.setClipPath(path)
        painter.drawPixmap(0, 0, cropped)
        painter.end()

        self.avatar.setText("")
        self.avatar.setPixmap(rounded)


class LivePage(QWidget):
    watch_requested = Signal(str, str)
    capture_source_changed = Signal(str, object)
    def __init__(self, parent=None):
        super().__init__(parent)

        self._presence_online = False
        self._stream_state = "idle"
        self._saved_live_settings = load_live_settings()
        self._capture_sources = {}

        self.setObjectName("livePage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setStyleSheet('\n    QWidget#livePage {\n        background-color: #101018;\n    }\n\n    QScrollArea#liveScrollArea {\n        background-color: #101018;\n        border: none;\n    }\n\n    QWidget#liveScrollViewport,\n    QWidget#liveFriendsContainer {\n        background-color: #101018;\n    }\n\n    QScrollBar:vertical {\n        background-color: #101018;\n        width: 9px;\n        margin: 2px;\n    }\n\n    QScrollBar::handle:vertical {\n        background-color: #39394D;\n        border-radius: 4px;\n        min-height: 28px;\n    }\n\n    QScrollBar::handle:vertical:hover {\n        background-color: #62577F;\n    }\n\n    QScrollBar::add-line:vertical,\n    QScrollBar::sub-line:vertical {\n        height: 0px;\n    }\n')

        self.friend_cards = {}
        self.avatar_cache = {}
        self.pending_avatars = set()

        self.network = QNetworkAccessManager(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(15)

        # -------------------------------------------------
        # CONEXÃO E TRANSMISSÃO
        # -------------------------------------------------

        connection_card = QFrame()
        connection_card.setObjectName("card")

        connection_layout = QHBoxLayout(connection_card)
        connection_layout.setContentsMargins(17, 15, 17, 15)

        connection_info = QVBoxLayout()
        connection_info.setSpacing(5)

        connection_title = QLabel("SUA PRESENÇA")
        connection_title.setObjectName("cardTitle")

        self.connection_label = QLabel("Conectando...")
        self.connection_label.setStyleSheet("""
            color: #e5bc71;
            font-size: 18px;
            font-weight: bold;
        """)

        self.connection_detail = QLabel(
            "Verificando conexão com o servidor."
        )
        self.connection_detail.setObjectName("muted")

        connection_info.addWidget(connection_title)
        connection_info.addWidget(self.connection_label)
        connection_info.addWidget(self.connection_detail)

        connection_layout.addLayout(connection_info, 1)

        self.share_button = QPushButton("Compartilhar tela")
        self.share_button.setObjectName("primaryButton")
        self.share_button.setEnabled(False)
        self.share_button.setToolTip(
            "A transmissão de vídeo será implementada na próxima etapa."
        )

        connection_layout.addWidget(self.share_button)

        root.addWidget(connection_card)

        # -------------------------------------------------
        # CONFIGURAÇÕES DA TRANSMISSÃO
        # -------------------------------------------------

        settings_card = QFrame()
        settings_card.setObjectName("card")
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(17, 14, 17, 14)
        settings_layout.setSpacing(10)

        settings_title = QLabel("CONFIGURAÇÕES DA TRANSMISSÃO")
        settings_title.setObjectName("cardTitle")
        settings_layout.addWidget(settings_title)

        window_row = QHBoxLayout()
        window_label = QLabel("Fonte")
        window_label.setMinimumWidth(65)

        self.window_combo = QComboBox()
        self.window_combo.setMinimumWidth(260)
        self.window_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.window_combo.setMinimumContentsLength(28)

        window_row.addWidget(window_label)
        window_row.addWidget(self.window_combo, 1)
        settings_layout.addLayout(window_row)

        quality_row = QHBoxLayout()

        fps_label = QLabel("Quadros por segundo")
        self.fps_combo = QComboBox()
        for fps in (15, 30, 60):
            self.fps_combo.addItem(f"{fps} FPS", fps)

        quality_label = QLabel("Qualidade")
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("Econômica", "Econômica")
        self.quality_combo.addItem("Equilibrada", "Equilibrada")
        self.quality_combo.addItem("Alta", "Alta")

        quality_row.addWidget(fps_label)
        quality_row.addWidget(self.fps_combo)
        quality_row.addSpacing(12)
        quality_row.addWidget(quality_label)
        quality_row.addWidget(self.quality_combo)
        quality_row.addStretch()

        settings_layout.addLayout(quality_row)

        self.live_settings_status = QLabel(
            "Selecione a janela que deseja transmitir."
        )
        self.live_settings_status.setObjectName("muted")
        settings_layout.addWidget(self.live_settings_status)

        self.fps_combo.setCurrentIndex(
            self.fps_combo.findData(self._saved_live_settings["fps"])
        )
        self.quality_combo.setCurrentIndex(
            self.quality_combo.findData(
                self._saved_live_settings["quality"]
            )
        )

        self.refresh_capture_windows()

        self.window_combo.currentIndexChanged.connect(
            self._save_live_preferences
        )
        self.window_combo.currentIndexChanged.connect(
            self._notify_capture_source_changed
        )

        self._capture_refresh_timer = QTimer(self)
        self._capture_refresh_timer.setInterval(5000)
        self._capture_refresh_timer.timeout.connect(
            self.refresh_capture_windows
        )
        self._capture_refresh_timer.start()
        self.fps_combo.currentIndexChanged.connect(
            self._save_live_preferences
        )
        self.quality_combo.currentIndexChanged.connect(
            self._save_live_preferences
        )

        root.addWidget(settings_card)

        # -------------------------------------------------
        # LISTA DE MEMBROS
        # -------------------------------------------------

        members_header = QHBoxLayout()

        members_title = QLabel("MEMBROS DO SERVIDOR")
        members_title.setObjectName("cardTitle")

        self.members_summary = QLabel("Carregando membros...")
        self.members_summary.setObjectName("muted")

        members_header.addWidget(members_title)
        members_header.addStretch()
        members_header.addWidget(self.members_summary)

        root.addLayout(members_header)

        self.empty_label = QLabel(
            "Nenhum membro encontrado."
        )
        self.empty_label.setObjectName("muted")
        self.empty_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        root.addWidget(self.empty_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("liveScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #101018;
                border: none;
            }
        """)

        # Fundo da área interna de rolagem.
        viewport = self.scroll_area.viewport()
        viewport.setObjectName("liveScrollViewport")
        viewport.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground,
            True
        )
        viewport.setAutoFillBackground(True)
        viewport.setStyleSheet(
            "background-color: #101018;"
        )

        # Container dos membros.
        self.friends_container = QWidget()
        self.friends_container.setObjectName(
            "liveFriendsContainer"
        )
        self.friends_container.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground,
            True
        )
        self.friends_container.setAutoFillBackground(True)
        self.friends_container.setStyleSheet(
            "background-color: #101018;"
        )

        self.friends_layout = QVBoxLayout(
            self.friends_container
        )

        self.friends_layout.setContentsMargins(0, 0, 0, 0)
        self.friends_layout.setSpacing(9)
        self.friends_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop
        )

        self.friends_layout.addStretch()

        # Instala o container uma única vez.
        self.scroll_area.setWidget(self.friends_container)

        root.addWidget(self.scroll_area, 1)

        self.scroll_area.hide()

    def refresh_capture_windows(self):
        saved = self._saved_live_settings
        current_key = self.window_combo.currentData()

        self.window_combo.blockSignals(True)
        self.window_combo.clear()
        self._capture_sources.clear()

        try:
            monitors = list_capture_monitors()
        except Exception as error:
            monitors = []
            self.live_settings_status.setText(
                f"Não foi possível listar monitores: {error}"
            )

        try:
            windows = list_capture_windows()
        except Exception as error:
            windows = []
            self.live_settings_status.setText(
                f"Não foi possível listar janelas: {error}"
            )

        # Monitores são fontes individuais, nunca combinados.
        for monitor in monitors:
            key = f"monitor::{monitor['id']}"
            self._capture_sources[key] = ("monitor", monitor)
            self.window_combo.addItem(monitor["display"], key)

        if monitors and windows:
            self.window_combo.insertSeparator(self.window_combo.count())

        for window in windows:
            key = f"window::{window['hwnd']}"
            self._capture_sources[key] = ("window", window)
            self.window_combo.addItem(window["display"], key)

        selected_key = (
            current_key
            if current_key in self._capture_sources
            else None
        )

        if selected_key is None:
            if saved.get("source_type") == "monitor":
                monitor_id = saved.get("monitor_id", "")
                if monitor_id:
                    selected_key = f"monitor::{monitor_id}"
            else:
                saved_title = saved.get("window_title", "")
                saved_process = saved.get("process_name", "")

                for key, (kind, info) in self._capture_sources.items():
                    if (
                        kind == "window"
                        and info["title"] == saved_title
                        and info["process_name"] == saved_process
                    ):
                        selected_key = key
                        break

        selected_index = (
            self.window_combo.findData(selected_key)
            if selected_key else -1
        )

        if selected_index >= 0:
            self.window_combo.setCurrentIndex(selected_index)
            selected_kind = self._capture_sources[selected_key][0]
            self.live_settings_status.setText(
                "Monitor salvo localizado."
                if selected_kind == "monitor"
                else "Janela salva localizada."
            )
        else:
            saved_source = (
                saved.get("monitor_id")
                if saved.get("source_type") == "monitor"
                else saved.get("window_title")
            )

            if saved_source:
                self.window_combo.insertItem(
                    0,
                    f"Fonte salva não encontrada — {saved_source}",
                    None,
                )
                self.window_combo.setCurrentIndex(0)
                self.live_settings_status.setText(
                    "A fonte salva não está disponível. Selecione outra."
                )
            else:
                self.window_combo.setCurrentIndex(-1)
                self.live_settings_status.setText(
                    f"{len(monitors)} monitor(es) e "
                    f"{len(windows)} janela(s) encontrados."
                )

        self.window_combo.blockSignals(False)

    def _save_live_preferences(self, *_):
        source = self._capture_sources.get(
            self.window_combo.currentData()
        )

        if source is None:
            return

        capture_type, source_info = source

        try:
            kwargs = (
                {"monitor_info": source_info}
                if capture_type == "monitor"
                else {"window_info": source_info}
            )

            self._saved_live_settings = save_live_settings(
                self.fps_combo.currentData(),
                self.quality_combo.currentData(),
                capture_type=capture_type,
                **kwargs,
            )
            self.live_settings_status.setText(
                "Preferências salvas automaticamente."
            )
        except Exception as error:
            self.live_settings_status.setText(
                f"Erro ao salvar preferências: {error}"
            )

    def _notify_capture_source_changed(self, *_):
        source = self._capture_sources.get(
            self.window_combo.currentData()
        )

        if source is None:
            return

        capture_type, source_info = source

        self.capture_source_changed.emit(
            str(capture_type),
            dict(source_info),
        )

    def get_stream_settings(self):
        source = self._capture_sources.get(
            self.window_combo.currentData()
        )

        if source is None:
            raise ValueError(
                "Selecione uma janela ou um monitor individual."
            )

        capture_type, source_info = source

        return {
            "capture_type": capture_type,
            "window_info": (
                dict(source_info) if capture_type == "window" else None
            ),
            "monitor_info": (
                dict(source_info) if capture_type == "monitor" else None
            ),
            "fps": int(self.fps_combo.currentData()),
            "quality": str(self.quality_combo.currentData()),
        }

    def set_connection_status(self, online, message):

        self._presence_online = online

        if online:
            self.connection_label.setText("Conectado")
            self.connection_label.setStyleSheet(
                'color: #70D9A5; font-size: 18px; font-weight: bold;'
            )
        else:
            self.connection_label.setText("Desconectado")
            self.connection_label.setStyleSheet(
                'color: #E8BF79; font-size: 18px; font-weight: bold;'
            )

        self.connection_detail.setText(message)

        self._update_share_button()


    def set_stream_state(self, state, message):

        self._stream_state = state

        self.share_button.setToolTip(message)

        self._update_share_button()


    def _update_share_button(self):

        states = {
            "connecting": ("Conectando...", False),
            "streaming": ("Parar transmissão", True),
            "stopping": ("Encerrando...", False),
            "error": ("Tentar novamente", self._presence_online),
            "idle": ("Compartilhar tela", self._presence_online),
        }

        text, enabled = states.get(
            self._stream_state,
            ("Compartilhar tela", self._presence_online),
        )

        self.share_button.setText(text)
        self.share_button.setEnabled(enabled)
    # -------------------------------------------------
    # MEMBROS
    # -------------------------------------------------

    def set_friends(self, friends):

        if not isinstance(friends, list):
            return

        active_count = sum(
            1 for friend in friends
            if friend.get("liveOnline")
        )

        self.members_summary.setText(
            f"{len(friends)} membros  •  "
            f"{active_count} online"
        )

        self.empty_label.setVisible(not friends)
        self.scroll_area.setVisible(bool(friends))

        received_ids = set()

        for friend in friends:

            if not isinstance(friend, dict):
                continue

            friend_id = friend.get("id")

            if not friend_id:
                continue

            received_ids.add(friend_id)

            card = self.friend_cards.get(friend_id)
            
            if card is None:
                card = LiveFriendCard(self)

                card.watch_requested.connect(
                    self.watch_requested.emit
                )

                self.friend_cards[friend_id] = card

                self.friends_layout.insertWidget(
                    self.friends_layout.count() - 1,
                    card,
                )

            if card is None:

                card = LiveFriendCard(self)

                self.friend_cards[friend_id] = card

                self.friends_layout.insertWidget(
                    self.friends_layout.count() - 1,
                    card,
                )

            avatar_url = card.update_friend(friend)

            if avatar_url:

                if avatar_url in self.avatar_cache:
                    card.set_avatar_pixmap(
                        self.avatar_cache[avatar_url]
                    )

                else:
                    self.load_avatar(avatar_url)

        # Remove membros que saíram do servidor.
        removed_ids = (
            set(self.friend_cards.keys()) - received_ids
        )

        for friend_id in removed_ids:

            card = self.friend_cards.pop(friend_id)

            self.friends_layout.removeWidget(card)
            card.deleteLater()

    # -------------------------------------------------
    # AVATARES
    # -------------------------------------------------

    def load_avatar(self, url):

        if not url:
            return

        if url in self.avatar_cache:
            return

        if url in self.pending_avatars:
            return

        self.pending_avatars.add(url)

        request = QNetworkRequest(QUrl(url))

        reply = self.network.get(request)

        reply.finished.connect(
            lambda current_reply=reply:
                self.on_avatar_loaded(current_reply)
        )

    def on_avatar_loaded(self, reply):

        url = reply.request().url().toString()

        self.pending_avatars.discard(url)

        if reply.error() == QNetworkReply.NetworkError.NoError:

            pixmap = QPixmap()

            if pixmap.loadFromData(bytes(reply.readAll())):

                self.avatar_cache[url] = pixmap

                for card in self.friend_cards.values():

                    if card.avatar_url == url:
                        card.set_avatar_pixmap(pixmap)

        reply.deleteLater()