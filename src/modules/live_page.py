from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtCore import Qt, QSize, QUrl, Signal

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
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
)


class LiveFriendCard(QFrame):
    watch_requested = Signal(str, str)
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setObjectName("liveFriendCard")
        self.avatar_url = ""

        self.setStyleSheet("""
            QFrame#liveFriendCard {
                background-color: #191925;
                border: 1px solid #2d2d40;
                border-radius: 10px;
            }

            QFrame#liveFriendCard:hover {
                border-color: #51417d;
            }

            QLabel#liveFriendName {
                color: #f0edf9;
                font-size: 13px;
                font-weight: bold;
            }

            QLabel#liveFriendUsername {
                color: #85849b;
                font-size: 11px;
            }

            QLabel#liveFriendDiscord {
                color: #9291a8;
                font-size: 10px;
            }

            QLabel#liveFriendStatus {
                font-size: 11px;
                font-weight: bold;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 12, 13, 12)
        layout.setSpacing(13)

        self.avatar = QLabel()
        self.avatar.setFixedSize(46, 46)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.avatar.setStyleSheet("""
            QLabel {
                background-color: #30284d;
                color: #d2c8ff;
                border-radius: 23px;
                font-size: 14px;
                font-weight: bold;
            }
        """)

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

        self.watch_button.setStyleSheet("""
            QPushButton {
                background-color: #30284d;
                color: #d2c8ff;
                border: 1px solid #51417d;
                border-radius: 7px;
                padding: 8px;
            }

            QPushButton:hover {
                background-color: #51417d;
            }

            QPushButton:disabled {
                color: #666477;
                background-color: #20202f;
                border-color: #303044;
            }
        """)

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
                "color: #70d6a1;"
            )
        else:
            self.status_label.setText("Offline")
            self.status_label.setStyleSheet(
                "color: #85849b;"
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
    def __init__(self, parent=None):
        super().__init__(parent)

        self._presence_online = False
        self._stream_state = "idle"

        self.setObjectName("livePage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setStyleSheet("""
            QWidget#livePage {
                background-color: #11111a;
            }

            QScrollArea#liveScrollArea {
                background-color: #11111a;
                border: none;
            }

            QWidget#liveScrollViewport {
                background-color: #11111a;
            }

            QWidget#liveFriendsContainer {
                background-color: #11111a;
            }

            QScrollBar:vertical {
                background-color: #11111a;
                width: 8px;
                margin: 0px;
            }

            QScrollBar::handle:vertical {
                background-color: #393950;
                border-radius: 4px;
                min-height: 25px;
            }

            QScrollBar::handle:vertical:hover {
                background-color: #62528e;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

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
                background-color: #11111a;
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
            "background-color: #11111a;"
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
            "background-color: #11111a;"
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

        note = QLabel(
            "A presença indica que o L Desktop está aberto. "
            "Isso não significa que o membro esteja transmitindo."
        )

        note.setObjectName("muted")
        note.setWordWrap(True)

        root.addWidget(note)

        self.scroll_area.hide()

    # -------------------------------------------------
    # ESTADO DA CONEXÃO
    # -------------------------------------------------


    def set_connection_status(self, online, message):

        self._presence_online = online

        if online:
            self.connection_label.setText("Conectado")
            self.connection_label.setStyleSheet(
                "color: #70d6a1; font-size: 18px; font-weight: bold;"
            )
        else:
            self.connection_label.setText("Desconectado")
            self.connection_label.setStyleSheet(
                "color: #e5bc71; font-size: 18px; font-weight: bold;"
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