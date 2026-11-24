
import asyncio
import threading
import time
import traceback

import mss
import requests

from PySide6.QtCore import QThread, Signal

from livekit import rtc

from core.service_config import API_BASE_URL
from modules.device import get_device_token


class LiveScreenPublisher(QThread):
    state_changed = Signal(str, str)

    FPS = 15
    MAX_BITRATE = 4_000_000

    def __init__(self, parent=None):
        super().__init__(parent)

        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        self.state_changed.emit(
            "connecting",
            "Solicitando autorização de transmissão."
        )

        try:
            asyncio.run(self._publish_screen())

        except Exception as error:
            traceback.print_exc()

            self.state_changed.emit(
                "error",
                f"Falha na transmissão: {error}"
            )

        else:
            self.state_changed.emit(
                "idle",
                "Transmissão encerrada."
            )

    async def _publish_screen(self):

        # Recupera o vínculo já existente.
        device_token = get_device_token()

        if not device_token:
            raise RuntimeError(
                "Este dispositivo não está vinculado ao Discord."
            )

        # Solicita autorização temporária ao backend.
        response = requests.post(
            f"{API_BASE_URL.rstrip('/')}/live/token",
            headers={
                "x-device-token": device_token
            },
            json={
                "mode": "publish"
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
                data.get("error", "Não foi possível autorizar a transmissão.")
            )

        server_url = data.get("serverUrl")
        access_token = data.get("token")

        if not server_url or not access_token:
            raise RuntimeError(
                "O servidor não forneceu os dados de conexão."
            )

        room = rtc.Room()
        video_source = None
        presence_stop = threading.Event()
        presence_thread = None

        def maintain_stream_presence():
            with requests.Session() as session:
                while not presence_stop.is_set():
                    try:
                        response = session.post(
                            f"{API_BASE_URL.rstrip('/')}/live/stream/heartbeat",
                            headers={"x-device-token": device_token},
                            timeout=3,
                        )
                        response.raise_for_status()

                        if not response.json().get("success"):
                            raise RuntimeError("Heartbeat recusado.")

                    except Exception as error:
                        print(f"[LIVE STREAM] Falha no heartbeat: {error}")

                    if presence_stop.wait(8):
                        break

        room.on(
            "local_track_published",
            lambda publication, track: print(
                f"[LIVE STREAM] TRACK PUBLICADA: "
                f"SID={publication.sid}, tipo={track.kind}"
            )
        )

        room.on(
            "local_track_unpublished",
            lambda publication: print(
                f"[LIVE STREAM] TRACK REMOVIDA: {publication.sid}"
            )
        )

        room.on(
            "connection_state_changed",
            lambda state: print(
                f"[LIVE STREAM] Estado ICE/RTC: {state}"
            )
        )

        room.on(
            "disconnected",
            lambda reason: print(
                f"[LIVE STREAM] Desconectado: {reason}"
            )
        )

        try:
            # Conecta à sala autorizada.
            room_options = rtc.RoomOptions(
                auto_subscribe=False,
            )

            await room.connect(
                server_url,
                access_token,
                room_options,
            )

            print("[LIVE STREAM] Conectado ao LiveKit.")

            # Captura o monitor principal.
            with mss.mss() as screen:

                if len(screen.monitors) < 2:
                    raise RuntimeError(
                        "Nenhum monitor disponível para captura."
                    )

                monitor = screen.monitors[1]

                width = monitor["width"]
                height = monitor["height"]

                print(
                    f"[LIVE STREAM] Monitor: "
                    f"{width}x{height}"
                )

                # Fonte otimizada para compartilhamento de tela.
                video_source = rtc.VideoSource(
                    width,
                    height,
                    is_screencast=True,
                )

                video_track = rtc.LocalVideoTrack.create_video_track(
                    "screen-share",
                    video_source,
                )

                options = rtc.TrackPublishOptions(
                    source=rtc.TrackSource.SOURCE_SCREENSHARE,

                    video_encoding=rtc.VideoEncoding(
                        max_bitrate=self.MAX_BITRATE,
                        max_framerate=self.FPS,
                    ),

                    video_codec=rtc.VideoCodec.H264,
                    simulcast=False,
                )

                # Publica a tela na sala.
                publication = await room.local_participant.publish_track(
                    video_track,
                    options,
                )

                print(
                    f"[LIVE STREAM] Tela publicada: "
                    f"{publication.sid}"
                )

                self.state_changed.emit(
                    "streaming",
                    "Sua tela está sendo transmitida."
                )

                presence_thread = threading.Thread(
                    target=maintain_stream_presence,
                    name="LiveStreamPresence",
                    daemon=True,
                )
                presence_thread.start()
                frame_interval = 1.0 / self.FPS

                frame_count = 0
                capture_started = time.monotonic()
                next_stats_at = capture_started + 5

                while not self._stop_event.is_set():

                    frame_start = time.perf_counter()

                    shot = screen.grab(monitor)

                    frame = rtc.VideoFrame(
                        width,
                        height,
                        rtc.VideoBufferType.BGRA,
                        shot.bgra,
                    )

                    video_source.capture_frame(
                        frame,
                        timestamp_us=time.monotonic_ns() // 1000,
                    )

                    frame_count += 1

                    # Mede a frequência de captura e envio à fonte local.
                    if frame_count % 30 == 0:
                        elapsed = time.monotonic() - capture_started
                        average_fps = frame_count / max(elapsed, 0.001)

                        print(
                            f"[LIVE STREAM] Quadros enviados à fonte: "
                            f"{frame_count} | FPS médio: {average_fps:.1f}"
                        )

                    # Consulta as estatísticas WebRTC.
                    if time.monotonic() >= next_stats_at:
                        try:
                            stats = await room.get_rtc_stats()

                            print(
                                f"[LIVE STREAM] Estatísticas de publicação: "
                                f"{stats.publisher_stats!r}"
                            )

                        except Exception as error:
                            print(
                                f"[LIVE STREAM] Erro ao consultar estatísticas: {error}"
                            )

                        next_stats_at = time.monotonic() + 5

                    elapsed_frame = time.perf_counter() - frame_start

                    await asyncio.sleep(
                        max(0, frame_interval - elapsed_frame)
                    )

                # Captura e envia os quadros continuamente.
                while not self._stop_event.is_set():

                    frame_start = time.perf_counter()
                    frame_count = 0
                    capture_started = time.monotonic()

                    shot = screen.grab(monitor)

                    frame = rtc.VideoFrame(
                        width,
                        height,
                        rtc.VideoBufferType.BGRA,
                        shot.bgra,
                    )

                    video_source.capture_frame(
                        frame,
                        timestamp_us=time.monotonic_ns() // 1000,
                    )

                    frame_count += 1

                    if frame_count % (self.FPS * 5) == 0:
                        elapsed = time.monotonic() - capture_started

                        print(
                            f"[LIVE STREAM] Quadros enviados à fonte: "
                            f"{frame_count} | "
                            f"Média: {frame_count / elapsed:.1f} FPS"
                        )

                    elapsed = time.perf_counter() - frame_start

                    await asyncio.sleep(
                        max(0, frame_interval - elapsed)
                    )

        finally:
            presence_stop.set()

            if presence_thread is not None:
                presence_thread.join(timeout=4)

            try:
                response = requests.post(
                    f"{API_BASE_URL.rstrip('/')}/live/stream/disconnect",
                    headers={"x-device-token": device_token},
                    timeout=5,
                )
                response.raise_for_status()
            except Exception as error:
                print(f"[LIVE STREAM] Falha ao limpar presença: {error}")

            try:
                await room.disconnect()
            finally:
                if video_source is not None:
                    await video_source.aclose()

            print("[LIVE STREAM] Conexão encerrada.")
