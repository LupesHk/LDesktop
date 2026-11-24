
import asyncio
import threading
import traceback

import requests

from livekit import rtc

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
)

from core.service_config import API_BASE_URL
from modules.device import get_device_token


class LiveScreenViewer(QThread):

    state_changed = Signal(str, str)
    frame_received = Signal(QImage)

    def __init__(self, target_user_id, parent=None):
        super().__init__(parent)

        self.target_user_id = str(target_user_id)
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            asyncio.run(self._watch())

        except Exception as error:
            traceback.print_exc()

            self.state_changed.emit(
                "error",
                str(error),
            )

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

        @room.on("track_subscribed")
        def on_track_subscribed(
            track,
            publication,
            participant,
        ):
            if track.kind != rtc.TrackKind.KIND_VIDEO:
                return

            print(
                f"[LIVE VIEWER] Vídeo recebido: "
                f"{publication.sid}"
            )

            self.state_changed.emit(
                "video",
                "Recebendo transmissão."
            )

            task = asyncio.create_task(
                self._receive_frames(track)
            )

            tasks.add(task)
            task.add_done_callback(tasks.discard)

        @room.on("disconnected")
        def on_disconnected(reason):
            print(f"[LIVE VIEWER] Desconectado: {reason}")
            self._stop_event.set()

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

            print("[LIVE VIEWER] Conexão encerrada.")

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


class LiveViewerDialog(QDialog):

    def __init__(self, user_id, display_name, parent=None):
        super().__init__(parent)

        self.setWindowTitle(
            f"L Desktop Live — {display_name}"
        )

        self.resize(1100, 700)
        self.setMinimumSize(650, 420)

        self.setStyleSheet("""
            QDialog {
                background-color: #11111a;
                color: #f0eff8;
            }

            QLabel#viewerStatus {
                color: #9291a8;
                font-size: 12px;
            }

            QLabel#viewerVideo {
                background-color: #08080e;
                border: 1px solid #2d2d40;
                border-radius: 10px;
                color: #9291a8;
            }
        """)

        self.last_image = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()

        title = QLabel(display_name)
        title.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #f5f2ff;
        """)

        self.status_label = QLabel("Iniciando...")
        self.status_label.setObjectName("viewerStatus")

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.status_label)

        layout.addLayout(header)

        self.video_label = QLabel(
            "Aguardando transmissão..."
        )

        self.video_label.setObjectName("viewerVideo")
        self.video_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        layout.addWidget(self.video_label, 1)

        footer = QHBoxLayout()
        footer.addStretch()

        close_button = QPushButton("Fechar")
        close_button.clicked.connect(self.close)

        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.viewer = LiveScreenViewer(
            user_id,
            self,
        )

        self.viewer.state_changed.connect(
            self.on_state_changed
        )

        self.viewer.frame_received.connect(
            self.on_frame_received
        )

        self.viewer.start()

    def on_state_changed(self, state, message):

        self.status_label.setText(message)

        if state == "error":
            self.status_label.setStyleSheet(
                "color: #e5bc71;"
            )

        elif state == "video":
            self.status_label.setStyleSheet(
                "color: #70d6a1;"
            )

    def on_frame_received(self, image):

        self.last_image = image
        self.render_frame()

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

        if self.viewer.isRunning():
            self.viewer.stop()
            self.viewer.wait()

        event.accept()
