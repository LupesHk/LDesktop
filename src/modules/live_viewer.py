import asyncio
import json
import threading
import traceback

import requests

from livekit import rtc

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QGuiApplication,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QSlider,
    QFrame,
    QSizeGrip,
)

from core.service_config import API_BASE_URL
from modules.device import get_device_token
from modules.live_audio_playback import LiveAudioPlayback


class LiveScreenViewer(QThread):

    state_changed = Signal(str, str)
    frame_received = Signal(QImage)
    audio_state_changed = Signal(str)
    audience_changed = Signal(object)

    def __init__(self, target_user_id, parent=None):
        super().__init__(parent)

        self.target_user_id = str(target_user_id)
        self._stop_event = threading.Event()
        self._audio_playback = None
        self._audio_volume = 1.0
        self._publisher_identity = None

    def _emit_audience(self, room):
        try:
            audience = []

            local = room.local_participant

            audience.append({
                "identity": str(local.identity),
                "name": "Você",
                "is_self": True,
            })

            remote = []

            for participant in list(room.remote_participants.values()):
                identity = str(
                    getattr(participant, "identity", "") or ""
                )

                if not identity:
                    continue

                if identity == self._publisher_identity:
                    continue

                publications = getattr(
                    participant,
                    "track_publications",
                    {},
                )

                is_publisher = any(
                    getattr(publication, "kind", None)
                    == rtc.TrackKind.KIND_VIDEO
                    for publication in publications.values()
                )

                if is_publisher:
                    self._publisher_identity = identity
                    continue

                name = str(
                    getattr(participant, "name", "") or ""
                ).strip()

                attributes = getattr(
                    participant,
                    "attributes",
                    {},
                ) or {}

                if not name:
                    for key in (
                        "displayName",
                        "display_name",
                        "username",
                        "name",
                    ):
                        value = attributes.get(key)
                        if value:
                            name = str(value).strip()
                            break

                if not name:
                    metadata = getattr(
                        participant,
                        "metadata",
                        "",
                    )

                    try:
                        metadata_data = json.loads(metadata)

                        if isinstance(metadata_data, dict):
                            for key in (
                                "displayName",
                                "display_name",
                                "username",
                                "name",
                            ):
                                value = metadata_data.get(key)
                                if value:
                                    name = str(value).strip()
                                    break
                    except (ValueError, TypeError):
                        pass

                if not name:
                    name = (
                        identity
                        if len(identity) <= 18
                        else identity[:10] + "?" + identity[-4:]
                    )

                remote.append({
                    "identity": identity,
                    "name": name,
                    "is_self": False,
                })

            remote.sort(
                key=lambda item: item["name"].casefold()
            )

            audience.extend(remote)
            self.audience_changed.emit(audience)

        except Exception as error:
            print(
                f"[LIVE VIEWER] Erro atualizando espectadores: {error}"
            )
    def stop(self):
        self._stop_event.set()

    def set_audio_volume(self, value):
        self._audio_volume = max(0.0, min(1.0, float(value)))

        if self._audio_playback is not None:
            self._audio_playback.set_volume(self._audio_volume)

    def run(self):
        try:
            asyncio.run(self._watch())

        except Exception as error:
            traceback.print_exc()

            self.state_changed.emit(
                "error",
                str(error),
            )

    def _mark_stream_ended(self, message):
        if self._stop_event.is_set():
            return

        print(f"[LIVE VIEWER] {message}")
        self._stop_event.set()
        self.state_changed.emit("ended", message)

    async def _watch(self):

        device_token = get_device_token()

        if not device_token:
            raise RuntimeError(
                "Dispositivo não vinculado ao Discord."
            )

        # Solicita autorização para assistir ao membro.
        response = requests.post(
            f"{API_BASE_URL.rstrip('/')}/live/token",
            headers={
                "x-device-token": device_token
            },
            json={
                "mode": "watch",
                "targetUserId": self.target_user_id,
            },
            timeout=15,
        )

        try:
            data = response.json()
        except ValueError as error:
            raise RuntimeError(
                "Resposta inválida do servidor."
            ) from error

        if response.status_code >= 400 or not data.get("success"):
            raise RuntimeError(
                data.get(
                    "error",
                    "Não foi possível acessar a transmissão."
                )
            )

        server_url = data.get("serverUrl")
        access_token = data.get("token")

        if not server_url or not access_token:
            raise RuntimeError(
                "Dados de conexão ausentes."
            )

        room = rtc.Room()
        tasks = set()

        @room.on("participant_connected")
        def on_participant_connected(participant):
            self._emit_audience(room)

        @room.on("participant_name_changed")
        def on_participant_name_changed(participant, old_name, new_name):
            self._emit_audience(room)

        @room.on("track_subscribed")
        def on_track_subscribed(
            track,
            publication,
            participant,
        ):
            if track.kind == rtc.TrackKind.KIND_VIDEO:
                if self._publisher_identity is None:
                    self._publisher_identity = participant.identity

                self._emit_audience(room)
                print(
                    f"[LIVE VIEWER] Vídeo recebido: {publication.sid}"
                )

                self.state_changed.emit(
                    "video",
                    "Recebendo transmissão.",
                )

                task = asyncio.create_task(
                    self._receive_frames(track)
                )

            elif track.kind == rtc.TrackKind.KIND_AUDIO:
                print(
                    f"[LIVE VIEWER] Áudio recebido: {publication.sid}"
                )

                try:
                    if self._audio_playback is None:
                        playback = LiveAudioPlayback()
                        playback.start()
                        playback.set_volume(self._audio_volume)
                        self._audio_playback = playback

                    self.audio_state_changed.emit("playing")

                except Exception as error:
                    print(
                        f"[LIVE VIEWER] Saída de áudio indisponível: {error}"
                    )
                    self.audio_state_changed.emit("error")
                    return

                task = asyncio.create_task(
                    self._receive_audio(track)
                )

            else:
                return

            tasks.add(task)
            task.add_done_callback(tasks.discard)

        @room.on("track_published")
        def on_track_published(publication, participant):
            if publication.kind == rtc.TrackKind.KIND_VIDEO:
                self._publisher_identity = participant.identity
                self._emit_audience(room)

        @room.on("participant_disconnected")
        def on_participant_disconnected(participant):
            identity = getattr(participant, "identity", None)

            if (
                self._publisher_identity is not None
                and identity == self._publisher_identity
            ):
                self._mark_stream_ended(
                    "O transmissor encerrou a transmissão."
                )

            self._emit_audience(room)

        @room.on("disconnected")
        def on_disconnected(reason):
            print(f"[LIVE VIEWER] Desconectado: {reason}")
            self._mark_stream_ended(
                "A conexão com a transmissão foi encerrada."
            )

        try:
            self.state_changed.emit(
                "connecting",
                "Conectando à transmissão..."
            )

            await room.connect(
                server_url,
                access_token,
                rtc.RoomOptions(auto_subscribe=True),
            )

            self._emit_audience(room)

            print(
                f"[LIVE VIEWER] Conectado à sala: {room.name}"
            )

            self.state_changed.emit(
                "waiting",
                "Conectado. Aguardando vídeo..."
            )

            # Aguarda quadros ou solicitação de encerramento.
            while not self._stop_event.is_set():
                await asyncio.sleep(0.1)

        finally:
            # Encerra os leitores de vídeo.
            for task in list(tasks):
                task.cancel()

            if tasks:
                await asyncio.gather(
                    *tasks,
                    return_exceptions=True,
                )

            if room.isconnected():
                await room.disconnect()

            if self._audio_playback is not None:
                self._audio_playback.stop()
                self._audio_playback = None

            self.audio_state_changed.emit("stopped")
            self.audience_changed.emit([])
            print("[LIVE VIEWER] Conexão encerrada.")

    async def _receive_audio(self, track):
        stream = rtc.AudioStream(
            track,
            sample_rate=48000,
            num_channels=2,
            frame_size_ms=10,
        )

        try:
            async for event in stream:
                if self._stop_event.is_set():
                    break

                playback = self._audio_playback

                if playback is None:
                    break

                if playback.error is not None:
                    raise RuntimeError(str(playback.error))

                playback.enqueue(event.frame.data)

        except asyncio.CancelledError:
            raise

        except Exception as error:
            print(
                f"[LIVE VIEWER] Erro no áudio recebido: {error}"
            )
            self.audio_state_changed.emit("error")

        finally:
            await stream.aclose()

    async def _receive_frames(self, track):

        stream = rtc.VideoStream(
            track,
            format=rtc.VideoBufferType.RGB24,
        )

        try:
            async for event in stream:

                if self._stop_event.is_set():
                    break

                frame = event.frame

                image = QImage(
                    bytes(frame.data),
                    frame.width,
                    frame.height,
                    frame.width * 3,
                    QImage.Format.Format_RGB888,
                ).copy()

                if not image.isNull():
                    self.frame_received.emit(image)

        except asyncio.CancelledError:
            raise

        except Exception as error:
            print(
                f"[LIVE VIEWER] Erro ao receber quadros: {error}"
            )

            self.state_changed.emit(
                "error",
                f"Erro ao receber vídeo: {error}"
            )

        finally:
            await stream.aclose()


class _LiveMiniDragBar(QFrame):
    """Barra superior que permite mover o mini player."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self.window().frameGeometry().topLeft()
            )
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.window().move(
                event.globalPosition().toPoint() - self._drag_offset
            )
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class _LiveMiniPlayer(QDialog):
    """Janela Picture-in-Picture."""

    restore_requested = Signal()
    close_requested = Signal()
    volume_changed = Signal(int)
    mute_requested = Signal()

    def __init__(self, display_name):
        super().__init__(None)

        self._allow_close = False
        self._last_image = None

        self.setObjectName("liveMiniPlayer")
        self.setWindowTitle(f"L Desktop Live - {display_name}")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMinimumSize(360, 240)
        self.resize(500, 320)

        self.setStyleSheet("""
            QDialog#liveMiniPlayer {
                background-color: #11111a;
                color: #f0eff8;
            }

            QFrame#miniShell {
                background-color: #171722;
                border: 1px solid #39334f;
                border-radius: 13px;
            }

            QFrame#miniDragBar {
                background-color: #201d30;
                border: none;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }

            QLabel#miniTitle {
                color: #f4f0ff;
                font-size: 12px;
                font-weight: bold;
            }

            QLabel#miniStatus {
                color: #70d6a1;
                font-size: 10px;
                font-weight: bold;
            }

            QLabel#miniVideo {
                background-color: #07070c;
                border: 1px solid #29293b;
                border-radius: 8px;
                color: #9291a8;
            }

            QLabel#miniAudioStatus {
                color: #a7a4bb;
                font-size: 10px;
            }

            QPushButton#miniIconButton {
                background-color: transparent;
                color: #d9d4eb;
                border: none;
                border-radius: 6px;
                min-width: 29px;
                max-width: 29px;
                min-height: 27px;
                max-height: 27px;
                font-size: 16px;
            }

            QPushButton#miniIconButton:hover {
                background-color: #39334f;
                color: white;
            }

            QPushButton#miniCloseButton {
                background-color: transparent;
                color: #c7c2d9;
                border: none;
                border-radius: 6px;
                min-width: 29px;
                max-width: 29px;
                min-height: 27px;
                max-height: 27px;
                font-size: 17px;
            }

            QPushButton#miniCloseButton:hover {
                background-color: #753b4b;
                color: white;
            }

            QPushButton#miniMuteButton {
                background-color: #282439;
                color: #ded9ed;
                border: 1px solid #403951;
                border-radius: 6px;
                padding: 5px 9px;
                font-size: 10px;
            }

            QPushButton#miniMuteButton:hover {
                background-color: #39334f;
            }

            QSlider::groove:horizontal {
                height: 4px;
                background: #363247;
                border-radius: 2px;
            }

            QSlider::sub-page:horizontal {
                background: #9474e8;
                border-radius: 2px;
            }

            QSlider::handle:horizontal {
                background: #d8caff;
                width: 11px;
                margin: -4px 0;
                border-radius: 5px;
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(7, 7, 7, 7)
        outer.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("miniShell")
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(1, 1, 1, 5)
        shell_layout.setSpacing(7)

        # Barra superior arrast?vel.
        self.drag_bar = _LiveMiniDragBar()
        self.drag_bar.setObjectName("miniDragBar")

        bar_layout = QHBoxLayout(self.drag_bar)
        bar_layout.setContentsMargins(11, 5, 6, 5)
        bar_layout.setSpacing(7)

        self.title_label = QLabel(display_name)
        self.title_label.setObjectName("miniTitle")
        self.title_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )

        self.status_label = QLabel("CONECTANDO")
        self.status_label.setObjectName("miniStatus")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )
        self.status_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )

        self.restore_button = QPushButton("⏹️")
        self.restore_button.setObjectName("miniIconButton")
        self.restore_button.setToolTip("Voltar ao visualizador completo")
        self.restore_button.clicked.connect(
            lambda: self.restore_requested.emit()
        )

        self.close_button = QPushButton("❌")
        self.close_button.setObjectName("miniCloseButton")
        self.close_button.setToolTip("Encerrar visualização")
        self.close_button.clicked.connect(
            lambda: self.close_requested.emit()
        )

        bar_layout.addWidget(self.title_label, 1)
        bar_layout.addWidget(self.status_label)
        bar_layout.addWidget(self.restore_button)
        bar_layout.addWidget(self.close_button)

        shell_layout.addWidget(self.drag_bar)

        # Imagem.
        self.video_label = QLabel("Aguardando transmissão...")
        self.video_label.setObjectName("miniVideo")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(250, 140)
        shell_layout.addWidget(self.video_label, 1)

        # Áudio.
        audio_layout = QHBoxLayout()
        audio_layout.setContentsMargins(9, 0, 9, 0)
        audio_layout.setSpacing(8)

        self.audio_status_label = QLabel("áudio aguardando")
        self.audio_status_label.setObjectName("miniAudioStatus")

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(105)
        self.volume_slider.valueChanged.connect(
            self.volume_changed.emit
        )

        self.mute_button = QPushButton("Silenciar")
        self.mute_button.setObjectName("miniMuteButton")
        self.mute_button.clicked.connect(
            lambda: self.mute_requested.emit()
        )

        audio_layout.addWidget(self.audio_status_label, 1)
        audio_layout.addWidget(self.volume_slider)
        audio_layout.addWidget(self.mute_button)

        shell_layout.addLayout(audio_layout)

        outer.addWidget(self.shell)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 2, 0)
        grip_row.addStretch()

        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(15, 15)
        grip_row.addWidget(self.size_grip)

        outer.addLayout(grip_row)

    def set_frame(self, image):
        if image is None or image.isNull():
            return

        self._last_image = image
        pixmap = QPixmap.fromImage(image)

        self.video_label.setText("")
        self.video_label.setPixmap(
            pixmap.scaled(
                self.video_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def set_status(self, state, message):
        labels = {
            "connecting": ("CONECTANDO", "#e5bc71"),
            "waiting": ("AGUARDANDO", "#c5c0d8"),
            "video": ("• AO VIVO", "#70d6a1"),
            "error": ("ERRO", "#e5bc71"),
            "ended": ("ENCERRADO", "#a7a4bb"),
        }

        text, color = labels.get(
            state,
            (str(state).upper(), "#a7a4bb"),
        )

        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: bold;"
        )
        self.status_label.setToolTip(message)

    def set_audio_state(self, state):
        labels = {
            "playing": "áudio ativo",
            "error": "áudio indisponível",
            "stopped": "áudio encerrado",
            "waiting": "áudio aguardando",
        }

        self.audio_status_label.setText(
            labels.get(state, "áudio")
        )

    def set_volume(self, value):
        previous = self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(int(value))
        self.volume_slider.blockSignals(previous)

        self.mute_button.setText(
            "Ativar áudio" if int(value) == 0 else "Silenciar"
        )

    def allow_close(self):
        self._allow_close = True

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if self._last_image is not None:
            pixmap = QPixmap.fromImage(self._last_image)
            self.video_label.setPixmap(
                pixmap.scaled(
                    self.video_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
            return

        # Fechar pelo X do Windows restaura o visualizador completo.
        event.ignore()
        self.restore_requested.emit()



class _LiveViewerVideoLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return

        super().mouseDoubleClickEvent(event)


class LiveViewerDialog(QDialog):


    def __init__(self, user_id, display_name, parent=None):
        super().__init__(parent)

        self.setObjectName("liveViewerDialog")
        self.setWindowTitle(f"L Desktop Live - {display_name}")
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)

        self.last_image = None
        self._audio_state = "waiting"
        self._closing = False
        self.is_picture_in_picture = False
        self.is_fullscreen = False

        self.setStyleSheet("""
            QDialog#liveViewerDialog {
                background-color: #0c0b12;
                color: #f0eff8;
            }

            QFrame#viewerHeader {
                background-color: #171421;
                border: 1px solid #302a40;
                border-radius: 15px;
            }

            QLabel#viewerBrand {
                color: #ac91ef;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 2px;
            }

            QLabel#viewerTitle {
                color: #f5f1ff;
                font-size: 20px;
                font-weight: 700;
            }

            QLabel#viewerSubtitle {
                color: #9790a9;
                font-size: 11px;
            }

            QLabel#viewerStatus {
                color: #c4b2f4;
                background-color: #282038;
                border: 1px solid #51406f;
                border-radius: 8px;
                padding: 8px 13px;
                font-size: 10px;
                font-weight: 800;
            }

            QFrame#viewerVideoStage {
                background-color: #050509;
                border: 1px solid #342b48;
                border-radius: 15px;
            }

            QLabel#viewerVideo {
                background-color: #050509;
                border: none;
                border-radius: 10px;
                color: #777287;
                font-size: 14px;
            }

            QFrame#viewerAudioPanel {
                background-color: #171421;
                border: 1px solid #302a40;
                border-radius: 12px;
            }

            QLabel#viewerAudioStatus {
                color: #a7a0b9;
                font-size: 11px;
                font-weight: 600;
            }

            QLabel#viewerVolumeLabel {
                color: #bdb5ce;
                font-size: 11px;
                font-weight: 600;
            }

            QLabel#viewerShortcutHint {
                color: #827b92;
                font-size: 10px;
            }

            QPushButton {
                background-color: #211e2e;
                color: #e8e2f5;
                border: 1px solid #3b344d;
                border-radius: 8px;
                padding: 9px 15px;
                min-height: 20px;
                font-size: 11px;
                font-weight: 600;
            }

            QPushButton:hover {
                background-color: #342b48;
                border-color: #705b99;
            }

            QPushButton:pressed {
                background-color: #44345e;
            }

            QPushButton#primaryViewerButton {
                background-color: #67499d;
                color: white;
                border: 1px solid #8465bd;
                font-weight: 700;
            }

            QPushButton#primaryViewerButton:hover {
                background-color: #7959b3;
                border-color: #a188d3;
            }

            QPushButton#viewerCloseButton {
                background-color: transparent;
                color: #aaa1ba;
                border: 1px solid #393243;
            }

            QPushButton#viewerCloseButton:hover {
                background-color: #492b3a;
                color: #ffffff;
                border-color: #87506a;
            }

            QSlider::groove:horizontal {
                height: 5px;
                background: #363044;
                border-radius: 2px;
            }

            QSlider::sub-page:horizontal {
                background: #9270d2;
                border-radius: 2px;
            }

            QSlider::handle:horizontal {
                background: #d8c5ff;
                width: 13px;
                height: 13px;
                margin: -5px 0;
                border-radius: 6px;
            }

            QSlider::handle:horizontal:hover {
                background: #ffffff;
            }
        """)

        # Layout principal
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(13)

        # --------------------------------------------------------
        # CABE?ALHO
        # --------------------------------------------------------

        header_frame = QFrame()
        header_frame.setObjectName("viewerHeader")

        header = QHBoxLayout(header_frame)
        header.setContentsMargins(18, 13, 18, 13)
        header.setSpacing(14)

        identity = QVBoxLayout()
        identity.setSpacing(3)

        brand = QLabel("L DESKTOP  /  LIVE")
        brand.setObjectName("viewerBrand")

        title = QLabel(display_name)
        title.setObjectName("viewerTitle")
        title.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        subtitle = QLabel("Compartilhando a tela")
        subtitle.setObjectName("viewerSubtitle")

        identity.addWidget(brand)
        identity.addWidget(title)
        identity.addWidget(subtitle)

        self.status_label = QLabel("CONECTANDO")
        self.status_label.setObjectName("viewerStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setMinimumWidth(140)

        header.addLayout(identity)
        header.addStretch()
        header.addWidget(self.status_label)

        root.addWidget(header_frame)

        # --------------------------------------------------------
        # PALCO DE VIDEO
        # --------------------------------------------------------

        self.video_stage = QFrame()
        self.video_stage.setObjectName("viewerVideoStage")

        stage_layout = QVBoxLayout(self.video_stage)
        stage_layout.setContentsMargins(8, 8, 8, 8)
        stage_layout.setSpacing(0)

        self.video_label = _LiveViewerVideoLabel(
            "Aguardando transmissão..."
        )
        self.video_label.setObjectName("viewerVideo")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setToolTip(
            "Duplo clique para alternar tela cheia"
        )
        self.video_label.double_clicked.connect(
            self.toggle_fullscreen
        )

        stage_layout.addWidget(self.video_label)
        root.addWidget(self.video_stage, 1)

        # --------------------------------------------------------
        # PAINEL DE AUDIO
        # --------------------------------------------------------

        audio_frame = QFrame()
        audio_frame.setObjectName("viewerAudioPanel")

        audio_controls = QHBoxLayout(audio_frame)
        audio_controls.setContentsMargins(17, 11, 17, 11)
        audio_controls.setSpacing(11)

        self.audio_status_label = QLabel("ÁUDIO  /  AGUARDANDO")
        self.audio_status_label.setObjectName("viewerAudioStatus")

        audio_controls.addWidget(self.audio_status_label)
        audio_controls.addStretch()

        self.volume_label = QLabel("VOLUME")
        self.volume_label.setObjectName("viewerVolumeLabel")

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(180)
        self._last_volume = 100

        self.mute_button = QPushButton("Silenciar")
        self.mute_button.setMinimumWidth(105)

        self.volume_slider.valueChanged.connect(
            self.on_volume_changed
        )
        self.mute_button.clicked.connect(
            self.toggle_audio_mute
        )

        audio_controls.addWidget(self.volume_label)
        audio_controls.addWidget(self.volume_slider)
        audio_controls.addWidget(self.mute_button)

        root.addWidget(audio_frame)

        # --------------------------------------------------------
        # RODAPE
        # --------------------------------------------------------

        footer = QHBoxLayout()
        footer.setSpacing(9)


        # Mural de espectadores
        self.audience_panel = QFrame()
        self.audience_panel.setObjectName("viewerAudiencePanel")
        self.audience_panel.setMinimumWidth(330)
        self.audience_panel.setMaximumWidth(520)
        self.audience_panel.setFixedHeight(68)

        self.audience_panel.setStyleSheet("""
            QFrame#viewerAudiencePanel {
                background-color: #171421;
                border: 1px solid #302a40;
                border-radius: 12px;
            }

            QLabel#viewerAudienceHeading {
                color: #bba5e9;
                font-size: 9px;
                font-weight: 800;
                letter-spacing: 1px;
            }

            QLabel#viewerAudienceCount {
                color: #a69bb9;
                font-size: 9px;
            }

            QFrame#viewerAudienceChip {
                background-color: #252033;
                border: 1px solid #423653;
                border-radius: 8px;
            }

            QLabel#viewerAudienceAvatar {
                color: #ffffff;
                background-color: #654a91;
                border: 1px solid #8465b2;
                border-radius: 11px;
                font-size: 10px;
                font-weight: 800;
            }

            QLabel#viewerAudienceName {
                color: #e2dced;
                font-size: 10px;
                font-weight: 600;
            }

            QLabel#viewerAudienceMore {
                color: #c5b0ee;
                background-color: #302641;
                border: 1px solid #514069;
                border-radius: 8px;
                padding: 5px 9px;
                font-size: 10px;
                font-weight: 800;
            }

            QLabel#viewerAudienceEmpty {
                color: #878097;
                font-size: 10px;
            }
        """)

        audience_layout = QVBoxLayout(self.audience_panel)
        audience_layout.setContentsMargins(10, 6, 10, 6)
        audience_layout.setSpacing(4)

        audience_header = QHBoxLayout()
        audience_header.setSpacing(7)

        audience_heading = QLabel("ASSISTINDO AGORA")
        audience_heading.setObjectName("viewerAudienceHeading")

        self.audience_count_label = QLabel("1 pessoa")
        self.audience_count_label.setObjectName("viewerAudienceCount")

        audience_header.addWidget(audience_heading)
        audience_header.addStretch()
        audience_header.addWidget(self.audience_count_label)

        audience_layout.addLayout(audience_header)

        self.audience_chips_frame = QFrame()
        self.audience_chips_frame.setStyleSheet(
            "QFrame { background: transparent; border: none; }"
        )

        self.audience_chips_layout = QHBoxLayout(
            self.audience_chips_frame
        )
        self.audience_chips_layout.setContentsMargins(0, 0, 0, 0)
        self.audience_chips_layout.setSpacing(5)

        audience_layout.addWidget(self.audience_chips_frame)

        footer.addWidget(self.audience_panel)
        footer.addStretch()

        self.fullscreen_shortcut = QShortcut(
            QKeySequence("F"), self
        )
        self.fullscreen_shortcut.setContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.fullscreen_shortcut.activated.connect(
            self.toggle_fullscreen
        )

        self.exit_fullscreen_shortcut = QShortcut(
            QKeySequence("Escape"), self
        )
        self.exit_fullscreen_shortcut.setContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.exit_fullscreen_shortcut.activated.connect(
            self.exit_fullscreen
        )

        self.fullscreen_button = QPushButton("Tela cheia")
        self.fullscreen_button.setObjectName("primaryViewerButton")
        self.fullscreen_button.setToolTip(
            "Entrar em tela cheia (F)"
        )
        self.fullscreen_button.clicked.connect(
            self.enter_fullscreen
        )

        self.pip_button = QPushButton("Mini player")
        self.pip_button.setObjectName("secondaryViewerButton")
        self.pip_button.setToolTip(
            "Manter a transmissão em uma janela flutuante"
        )
        self.pip_button.clicked.connect(
            self.enter_picture_in_picture
        )

        close_button = QPushButton("Fechar")
        close_button.setObjectName("viewerCloseButton")
        close_button.clicked.connect(self.close)

        footer.addWidget(self.fullscreen_button)
        footer.addWidget(self.pip_button)
        footer.addWidget(close_button)

        root.addLayout(footer)

        # --------------------------------------------------------
        # PICTURE-IN-PICTURE
        # --------------------------------------------------------

        self.mini_player = _LiveMiniPlayer(display_name)
        self.mini_player.restore_requested.connect(
            self.exit_picture_in_picture
        )
        self.mini_player.close_requested.connect(self.close)
        self.mini_player.volume_changed.connect(
            self.volume_slider.setValue
        )
        self.mini_player.mute_requested.connect(
            self.toggle_audio_mute
        )

        # --------------------------------------------------------
        # LIVEKIT
        # --------------------------------------------------------

        self.viewer = LiveScreenViewer(user_id, self)

        self.viewer.state_changed.connect(self.on_state_changed)
        self.viewer.frame_received.connect(self.on_frame_received)
        self.viewer.audio_state_changed.connect(
            self.on_audio_state_changed
        )
        self.viewer.audience_changed.connect(self.set_audience)

        self.set_audience([
            {
                "identity": "local",
                "name": "Você",
                "is_self": True,
            }
        ])

        self.viewer.set_audio_volume(
            self.volume_slider.value() / 100.0
        )

        self.viewer.start()

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        if (
            self._closing
            or self.is_picture_in_picture
            or self.is_fullscreen
        ):
            return

        self.is_fullscreen = True
        self.fullscreen_button.setText("Sair da tela cheia")

        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.render_frame()

    def exit_fullscreen(self):
        if not self.is_fullscreen:
            return

        self.is_fullscreen = False
        self.fullscreen_button.setText("Tela cheia")

        if self._closing:
            return

        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.render_frame()

    def set_audience(self, participants):
        if not hasattr(self, "audience_chips_layout"):
            return

        participants = list(participants or [])

        # Remove os chips anteriores sem reconstruir o painel.
        while self.audience_chips_layout.count():
            item = self.audience_chips_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        count = len(participants)

        self.audience_count_label.setText(
            f"{count} pessoa" if count == 1
            else f"{count} pessoas"
        )

        if not participants:
            empty = QLabel("Ninguém assistindo no momento")
            empty.setObjectName("viewerAudienceEmpty")
            self.audience_chips_layout.addWidget(empty)
            self.audience_chips_layout.addStretch()
            return

        visible = participants[:3]

        for participant in visible:
            name = str(
                participant.get("name") or "Membro"
            ).strip()

            identity = str(
                participant.get("identity") or ""
            )

            is_self = bool(participant.get("is_self"))

            initials = "".join(
                part[0] for part in name.split()[:2]
                if part
            ).upper() or "?"

            chip = QFrame()
            chip.setObjectName("viewerAudienceChip")
            chip.setFixedHeight(29)
            chip.setToolTip(
                "Você" if is_self else f"{name} ? {identity}"
            )

            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(5, 2, 7, 2)
            chip_layout.setSpacing(6)

            avatar = QLabel(initials)
            avatar.setObjectName("viewerAudienceAvatar")
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setFixedSize(22, 22)

            if is_self:
                avatar.setStyleSheet(
                    "color: white; background-color: #7956ac;"
                    "border: 1px solid #a184d3; border-radius: 11px;"
                    "font-size: 10px; font-weight: 800;"
                )

            name_label = QLabel(name)
            name_label.setObjectName("viewerAudienceName")
            name_label.setMaximumWidth(85)
            name_label.setToolTip(name)

            chip_layout.addWidget(avatar)
            chip_layout.addWidget(name_label)

            self.audience_chips_layout.addWidget(chip)

        remaining = count - len(visible)

        if remaining > 0:
            more = QLabel(f"+{remaining}")
            more.setObjectName("viewerAudienceMore")
            more.setAlignment(Qt.AlignmentFlag.AlignCenter)
            more.setToolTip(
                f"Mais {remaining} pessoa(s) assistindo"
            )
            self.audience_chips_layout.addWidget(more)

        self.audience_chips_layout.addStretch()
    def enter_picture_in_picture(self):
        if self._closing or self.is_picture_in_picture:
            return

        if self.is_fullscreen:
            self.exit_fullscreen()

        self.is_picture_in_picture = True

        if self.last_image is not None:
            self.mini_player.set_frame(self.last_image)

        self.mini_player.set_volume(
            self.volume_slider.value()
        )
        self.mini_player.set_audio_state(self._audio_state)

        screen = self.screen() or QGuiApplication.primaryScreen()

        if screen is not None:
            area = screen.availableGeometry()
            margin = 22
            self.mini_player.move(
                area.right() - self.mini_player.width() - margin,
                area.bottom() - self.mini_player.height() - margin,
            )

        # Mostra a nova janela antes de esconder a anterior.
        self.mini_player.show()
        self.mini_player.raise_()
        self.hide()

    def exit_picture_in_picture(self):
        if self._closing or not self.is_picture_in_picture:
            return

        self.is_picture_in_picture = False
        self.mini_player.hide()

        self.showNormal()
        self.raise_()
        self.activateWindow()

    def on_audio_state_changed(self, state):
        self._audio_state = state
        self.mini_player.set_audio_state(state)

        if state == "playing":
            self.audio_status_label.setText("• Ao vivo")
            self.audio_status_label.setStyleSheet(
                "color: #70d6a1; font-size: 12px;"
            )

        elif state == "error":
            self.audio_status_label.setText("áudio indisponível")
            self.audio_status_label.setStyleSheet(
                "color: #e5bc71; font-size: 12px;"
            )

        elif state == "stopped":
            self.audio_status_label.setText("áudio encerrado")

    def on_volume_changed(self, value):
        self.viewer.set_audio_volume(value / 100.0)
        self.mini_player.set_volume(value)

        if value > 0:
            self._last_volume = value
            self.mute_button.setText("Silenciar")
        else:
            self.mute_button.setText("Ativar áudio")

    def toggle_audio_mute(self):
        if self.volume_slider.value() > 0:
            self._last_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)
        else:
            self.volume_slider.setValue(max(1, self._last_volume))

    def on_state_changed(self, state, message):
        self.status_label.setText(message)
        self.mini_player.set_status(state, message)

        if state == "ended":
            self.close()
            return

        if state == "error":
            self.status_label.setStyleSheet("color: #e5bc71;")

        elif state == "video":
            self.status_label.setStyleSheet("color: #70d6a1;")

    def on_frame_received(self, image):
        self.last_image = image

        if self.isVisible():
            self.render_frame()

        if self.is_picture_in_picture:
            self.mini_player.set_frame(image)

    def render_frame(self):
        if self.last_image is None:
            return

        pixmap = QPixmap.fromImage(self.last_image)
        self.video_label.setPixmap(
            pixmap.scaled(
                self.video_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_frame()

    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return

        self._closing = True
        self.is_picture_in_picture = False
        self.is_fullscreen = False

        self.mini_player.allow_close()
        self.mini_player.close()

        if self.viewer.isRunning():
            self.viewer.stop()
            self.viewer.wait()

        event.accept()
