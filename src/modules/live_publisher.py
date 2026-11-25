import asyncio
import threading
import time
import traceback

import requests

from PySide6.QtCore import QThread, Signal
from livekit import rtc
from PIL import Image

from core.service_config import API_BASE_URL
from core.live_settings import QUALITY_BITRATES, FPS_OPTIONS
from modules.device import get_device_token
from modules.live_capture import WindowCapture, MonitorCapture, WgcMonitorCapture
from modules.live_audio_capture import LiveAudioCapture


class LiveScreenPublisher(QThread):
    state_changed = Signal(str, str)

    def __init__(
        self,
        window_info=None,
        fps=15,
        quality="Equilibrada",
        capture_type="window",
        monitor_info=None,
        parent=None,
    ):
        super().__init__(parent)

        self.window_info = dict(window_info or {})
        self.capture_type = str(capture_type)
        self.monitor_info = dict(monitor_info or {})
        self.fps = int(fps)
        self.quality = quality
        self.max_bitrate = QUALITY_BITRATES.get(quality)

        if self.fps not in FPS_OPTIONS:
            raise ValueError("FPS deve ser 15, 30 ou 60.")

        if self.max_bitrate is None:
            raise ValueError("Qualidade de transmissão inválida.")

        if self.capture_type not in ("window", "monitor"):
            raise ValueError("Fonte de captura inválida.")

        if (
            self.capture_type == "window"
            and not self.window_info.get("hwnd")
        ):
            raise ValueError("Selecione uma janela para transmitir.")

        if (
            self.capture_type == "monitor"
            and not self.monitor_info.get("id")
        ):
            raise ValueError("Selecione um monitor para transmitir.")

        self._stop_event = threading.Event()
        self._capture_change_lock = threading.Lock()
        self._pending_capture_source = None
        self._capture_worker = None

    def stop(self):
        self._stop_event.set()
        worker = self._capture_worker
        if worker is not None:
            worker.stop()

    def _take_pending_capture_source(self):
        with self._capture_change_lock:
            pending = self._pending_capture_source
            self._pending_capture_source = None
            return pending

    def request_capture_source(self, capture_type, source_info):
        capture_type = str(capture_type)
        source_info = dict(source_info or {})

        if capture_type not in ("window", "monitor"):
            raise ValueError("Tipo de fonte inv?lido.")

        if capture_type == "window" and not source_info.get("hwnd"):
            raise ValueError("Janela selecionada inv?lida.")

        if capture_type == "monitor" and not source_info.get("id"):
            raise ValueError("Monitor selecionado inv?lido.")

        with self._capture_change_lock:
            self._pending_capture_source = (
                capture_type,
                source_info,
            )

        print(
            f"[LIVE STREAM] Troca de fonte solicitada: "
            f"{capture_type} | "
            f"{source_info.get('title') or source_info.get('display')}"
        )

    @staticmethod
    def _fit_bgra_frame(
        raw_frame,
        source_width,
        source_height,
        target_width,
        target_height,
    ):
        if (
            source_width == target_width
            and source_height == target_height
        ):
            return raw_frame

        expected = source_width * source_height * 4
        if len(raw_frame) != expected:
            raise ValueError(
                "O tamanho do quadro ? incompat?vel com a captura."
            )

        image = Image.frombytes(
            "RGB",
            (source_width, source_height),
            raw_frame,
            "raw",
            "BGRX",
        )

        scale = min(
            target_width / source_width,
            target_height / source_height,
        )

        resized_width = max(
            1,
            min(target_width, round(source_width * scale)),
        )
        resized_height = max(
            1,
            min(target_height, round(source_height * scale)),
        )

        image = image.resize(
            (resized_width, resized_height),
            Image.Resampling.BILINEAR,
        )

        canvas = Image.new(
            "RGB",
            (target_width, target_height),
            (0, 0, 0),
        )

        x = (target_width - resized_width) // 2
        y = (target_height - resized_height) // 2
        canvas.paste(image, (x, y))

        return canvas.convert("RGBA").tobytes("raw", "BGRA")

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
        device_token = get_device_token()

        if not device_token:
            raise RuntimeError(
                "Este dispositivo não está vinculado ao Discord."
            )

        response = requests.post(
            f"{API_BASE_URL.rstrip('/')}/live/token",
            headers={"x-device-token": device_token},
            json={"mode": "publish"},
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
        capture_worker = None

        audio_source = None
        audio_capture = None
        audio_task = None

        presence_stop = threading.Event()
        presence_thread = None

        def maintain_stream_presence():
            with requests.Session() as session:
                while not presence_stop.is_set():
                    try:
                        heartbeat = session.post(
                            f"{API_BASE_URL.rstrip('/')}/live/stream/heartbeat",
                            headers={"x-device-token": device_token},
                            timeout=3,
                        )
                        heartbeat.raise_for_status()

                        if not heartbeat.json().get("success"):
                            raise RuntimeError("Heartbeat recusado.")

                    except Exception as error:
                        print(
                            f"[LIVE STREAM] Falha no heartbeat: {error}"
                        )

                    if presence_stop.wait(8):
                        break

        room.on(
            "local_track_published",
            lambda publication, track: print(
                f"[LIVE STREAM] Track publicada: {publication.sid}"
            )
        )

        room.on(
            "connection_state_changed",
            lambda state: print(
                f"[LIVE STREAM] Estado RTC: {state}"
            )
        )

        try:
            await room.connect(
                server_url,
                access_token,
                rtc.RoomOptions(auto_subscribe=False),
            )

            print("[LIVE STREAM] Conectado ao LiveKit.")

            loop = asyncio.get_running_loop()
            frame_event = asyncio.Event()

            capture_worker = _LiveVideoCaptureThread(
                capture_type=self.capture_type,
                window_info=self.window_info,
                monitor_info=self.monitor_info,
                fps=self.fps,
                take_pending_source=self._take_pending_capture_source,
                loop=loop,
                frame_event=frame_event,
                state_signal=self.state_changed,
            )

            self._capture_worker = capture_worker
            capture_worker.start()

            startup_deadline = loop.time() + 15

            while not capture_worker.ready_event.is_set():
                if self._stop_event.is_set():
                    capture_worker.stop()

                if loop.time() >= startup_deadline:
                    raise RuntimeError(
                        "A thread de captura de video nao inicializou."
                    )

                await asyncio.sleep(0.01)

            if capture_worker.error is not None:
                raise RuntimeError(
                    f"Falha ao iniciar captura: {capture_worker.error}"
                )

            width = capture_worker.width
            height = capture_worker.height
            source_label = capture_worker.source_label

            if self._stop_event.is_set():
                capture_worker.stop()

            print(f"[LIVE STREAM] Fonte: {source_label}")
            print(
                f"[LIVE STREAM] Resolução: {width}x{height} | "
                f"FPS: {self.fps} | Bitrate máximo: "
                f"{self.max_bitrate / 1_000_000:.1f} Mbps"
            )

            video_source = rtc.VideoSource(
                width,
                height,
                is_screencast=True,
            )

            video_track = rtc.LocalVideoTrack.create_video_track(
                "window-share",
                video_source,
            )

            options = rtc.TrackPublishOptions(
                source=rtc.TrackSource.SOURCE_SCREENSHARE,
                video_encoding=rtc.VideoEncoding(
                    max_bitrate=self.max_bitrate,
                    max_framerate=self.fps,
                ),
                video_codec=rtc.VideoCodec.H264,
                simulcast=False,
            )

            publication = await room.local_participant.publish_track(
                video_track,
                options,
            )

            print(
                f"[LIVE STREAM] Janela publicada: {publication.sid}"
            )

            try:
                print("[LIVE AUDIO DEBUG] Etapa 1: criando capturador.")
                audio_capture = LiveAudioCapture()
                await audio_capture.start()
                print("[LIVE AUDIO DEBUG] Etapa 2: captura iniciada.")

                print("[LIVE AUDIO DEBUG] Etapa 3: criando AudioSource.")
                audio_source = rtc.AudioSource(
                    sample_rate=48000,
                    num_channels=2,
                    queue_size_ms=500,
                    loop=asyncio.get_running_loop(),
                )

                print("[LIVE AUDIO DEBUG] Etapa 4: AudioSource criado.")
                audio_track = rtc.LocalAudioTrack.create_audio_track(
                    "system-audio",
                    audio_source,
                )

                print("[LIVE AUDIO DEBUG] Etapa 5: AudioTrack criado.")
                audio_options = rtc.TrackPublishOptions(
                    source=rtc.TrackSource.SOURCE_SCREENSHARE_AUDIO
                )

                print("[LIVE AUDIO DEBUG] Etapa 6: publicando faixa.")
                audio_publication = (
                    await room.local_participant.publish_track(
                        audio_track,
                        audio_options,
                    )
                )

                print(
                    f"[LIVE AUDIO] Faixa de áudio publicada: "
                    f"{audio_publication.sid}"
                )

                print("[LIVE AUDIO DEBUG] Etapa 7: faixa publicada.")

                async def pump_audio():
                    try:
                        while not self._stop_event.is_set():
                            pcm = await audio_capture.get_frame()

                            frame = rtc.AudioFrame(
                                data=pcm,
                                sample_rate=48000,
                                num_channels=2,
                                samples_per_channel=480,
                            )

                            await audio_source.capture_frame(frame)

                    except asyncio.CancelledError:
                        raise

                    except Exception as error:
                        print(
                            f"[LIVE AUDIO] Captura interrompida: {error}"
                        )

                audio_task = asyncio.create_task(
                    pump_audio(),
                    name="LiveSystemAudioPublisher",
                )

            except Exception as error:
                print("[LIVE AUDIO DEBUG] EXCEÇÃO NA INICIALIZAÇÃO:")
                traceback.print_exc()
                print(
                    f"[LIVE AUDIO] Áudio indisponível; "
                    f"vídeo continuará normalmente: {error}"
                )

                if audio_capture is not None:
                    try:
                        await audio_capture.stop()
                    except Exception as stop_error:
                        print(
                            f"[LIVE AUDIO] Erro ao encerrar auxiliar: "
                            f"{stop_error}"
                        )
                        traceback.print_exc()

                if audio_source is not None:
                    try:
                        await audio_source.aclose()
                    except Exception:
                        pass

                audio_capture = None
                audio_source = None
                audio_task = None

            self.state_changed.emit(
                "streaming",
                f"Transmitindo janela a {self.fps} FPS."
            )

            presence_thread = threading.Thread(
                target=maintain_stream_presence,
                name="LiveStreamPresence",
                daemon=True,
            )
            presence_thread.start()

            started_at = time.monotonic()
            next_stats_at = started_at + 10
            last_sequence = 0


            print(
                "[LIVE STREAM] Captura de video isolada em thread propria."
            )

            while not self._stop_event.is_set():
                # Aguarda novos quadros sem bloquear as tarefas de audio.
                await frame_event.wait()
                frame_event.clear()

                if self._stop_event.is_set():
                    break

                sequence, raw_frame, capture_error = (
                    capture_worker.get_snapshot()
                )

                if capture_error is not None:
                    raise RuntimeError(
                        f"Captura de video interrompida: {capture_error}"
                    ) from capture_error

                if raw_frame is None or sequence == last_sequence:
                    continue

                frame = rtc.VideoFrame(
                    width,
                    height,
                    rtc.VideoBufferType.BGRA,
                    raw_frame,
                )

                video_source.capture_frame(
                    frame,
                    timestamp_us=time.monotonic_ns() // 1000,
                )

                last_sequence = sequence
                if time.monotonic() >= next_stats_at:
                    try:
                        stats = await room.get_rtc_stats()
                        print(
                            f"[LIVE STREAM] Estatisticas: "
                            f"{stats.publisher_stats!r}"
                        )
                    except Exception as error:
                        print(
                            f"[LIVE STREAM] Erro nas estatisticas: {error}"
                        )

                    next_stats_at = time.monotonic() + 10

        finally:
            if capture_worker is not None:
                capture_worker.stop()

                capture_deadline = loop.time() + 5

                while (
                    capture_worker.is_alive()
                    and loop.time() < capture_deadline
                ):
                    await asyncio.sleep(0.025)

                if (
                    not capture_worker.is_alive()
                    and capture_worker.ident is not None
                ):
                    capture_worker.join()
                    if self._capture_worker is capture_worker:
                        self._capture_worker = None
                else:
                    print(
                        "[LIVE STREAM] Aviso: thread de captura "
                        "nao encerrou no prazo."
                    )

            if audio_task is not None:
                audio_task.cancel()
                await asyncio.gather(
                    audio_task,
                    return_exceptions=True,
                )

            if audio_capture is not None:
                try:
                    await audio_capture.stop()
                except Exception as error:
                    print(
                        f"[LIVE AUDIO] Erro ao parar captura: {error}"
                    )

            presence_stop.set()

            if presence_thread is not None:
                presence_thread.join(timeout=4)

            try:
                disconnect = requests.post(
                    f"{API_BASE_URL.rstrip('/')}/live/stream/disconnect",
                    headers={"x-device-token": device_token},
                    timeout=5,
                )
                disconnect.raise_for_status()
            except Exception as error:
                print(
                    f"[LIVE STREAM] Falha ao limpar presença: {error}"
                )

            try:
                await room.disconnect()
            finally:
                if audio_source is not None:
                    await audio_source.aclose()

                if video_source is not None:
                    await video_source.aclose()


            print("[LIVE STREAM] Conexão encerrada.")

class _LiveVideoCaptureThread(threading.Thread):
    """Captura video fora do event loop do LiveKit."""

    def __init__(
        self,
        capture_type,
        window_info,
        monitor_info,
        fps,
        take_pending_source,
        loop,
        frame_event,
        state_signal,
    ):
        super().__init__(
            name="LiveVideoCapture",
            daemon=True,
        )

        self.capture_type = str(capture_type)
        self.window_info = dict(window_info or {})
        self.monitor_info = dict(monitor_info or {})
        self.fps = int(fps)

        self._take_pending_source = take_pending_source
        self._loop = loop
        self._frame_event = frame_event
        self._state_signal = state_signal

        self._stop_event = threading.Event()
        self.ready_event = threading.Event()

        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._sequence = 0
        self.error = None

        self._notification_lock = threading.Lock()
        self._notification_pending = False

        self.width = 0
        self.height = 0
        self.source_label = ""

    def stop(self):
        self._stop_event.set()
        self._notify_frame_ready()

    def get_snapshot(self):
        with self._frame_lock:
            return (
                self._sequence,
                self._latest_frame,
                self.error,
            )

    def _deliver_frame_notification(self):
        with self._notification_lock:
            self._notification_pending = False

        self._frame_event.set()

    def _notify_frame_ready(self):
        with self._notification_lock:
            if self._notification_pending:
                return

            self._notification_pending = True

        try:
            self._loop.call_soon_threadsafe(
                self._deliver_frame_notification
            )
        except RuntimeError:
            with self._notification_lock:
                self._notification_pending = False

            self._stop_event.set()

    def _store_frame(self, frame):
        with self._frame_lock:
            self._latest_frame = frame
            self._sequence += 1

        self._notify_frame_ready()

    @staticmethod
    def _create_capture(capture_type, source_info):
        if capture_type == "monitor":
            try:
                capture = WgcMonitorCapture(source_info)
                print(
                    f"[LIVE STREAM] Captura de monitor via "
                    f"{capture.backend}: {capture.width}x{capture.height}"
                )
            except Exception as error:
                print(
                    "[LIVE STREAM] WGC indispon?vel; usando GDI: "
                    f"{error}"
                )
                capture = MonitorCapture(source_info)
            label = source_info.get(
                "display",
                source_info.get("id", "Monitor"),
            )
        else:
            capture = WindowCapture(source_info["hwnd"])
            label = source_info.get("title", "Janela")

        return capture, label

    def _prepare_frame(self, raw_frame, source_width, source_height):
        expected = source_width * source_height * 4

        if len(raw_frame) != expected:
            raise RuntimeError(
                "A captura retornou um quadro de tamanho invalido."
            )

        return LiveScreenPublisher._fit_bgra_frame(
            raw_frame,
            source_width,
            source_height,
            self.width,
            self.height,
        )

    def run(self):
        capture = None

        try:
            source_info = (
                self.monitor_info
                if self.capture_type == "monitor"
                else self.window_info
            )

            capture, self.source_label = self._create_capture(
                self.capture_type,
                source_info,
            )

            self.width = int(capture.width)
            self.height = int(capture.height)

            if self.width <= 0 or self.height <= 0:
                raise RuntimeError(
                    "Dimensoes invalidas da fonte de video."
                )

            # Validar a fonte antes de considerar a thread pronta.
            first_frame = capture.grab()
            first_frame = self._prepare_frame(
                first_frame,
                self.width,
                self.height,
            )

            self._store_frame(first_frame)
            self.ready_event.set()

            interval = 1.0 / self.fps
            next_frame_at = time.perf_counter() + interval

            while not self._stop_event.is_set():
                delay = next_frame_at - time.perf_counter()

                if delay > 0 and self._stop_event.wait(delay):
                    break

                if self._stop_event.is_set():
                    break

                frame_data = None
                pending = self._take_pending_source()

                if pending is not None:
                    next_type, next_info = pending
                    next_capture = None

                    try:
                        next_capture, next_label = self._create_capture(
                            next_type,
                            next_info,
                        )

                        next_width = int(next_capture.width)
                        next_height = int(next_capture.height)

                        if next_width <= 0 or next_height <= 0:
                            raise RuntimeError(
                                "Dimensoes invalidas da nova fonte."
                            )

                        new_raw = next_capture.grab()
                        frame_data = self._prepare_frame(
                            new_raw,
                            next_width,
                            next_height,
                        )

                        previous_capture = capture
                        capture = next_capture
                        next_capture = None

                        self.capture_type = next_type
                        self.window_info = (
                            dict(next_info)
                            if next_type == "window" else {}
                        )
                        self.monitor_info = (
                            dict(next_info)
                            if next_type == "monitor" else {}
                        )
                        self.source_label = next_label

                        try:
                            previous_capture.close()
                        except Exception as close_error:
                            print(
                                "[LIVE STREAM] Erro liberando fonte "
                                f"anterior: {close_error}"
                            )

                        self._state_signal.emit(
                            "streaming",
                            f"Transmitindo {next_label} a {self.fps} FPS.",
                        )

                        print(
                            "[LIVE STREAM] Fonte alterada na thread "
                            f"de captura: {next_label}"
                        )

                    except Exception as error:
                        if next_capture is not None:
                            try:
                                next_capture.close()
                            except Exception:
                                pass

                        frame_data = None

                        print(
                            "[LIVE STREAM] Falha ao trocar fonte; "
                            f"mantendo a anterior: {error}"
                        )

                if frame_data is None:
                    raw = capture.grab()
                    frame_data = self._prepare_frame(
                        raw,
                        capture.width,
                        capture.height,
                    )

                self._store_frame(frame_data)

                next_frame_at += interval
                now = time.perf_counter()

                if next_frame_at < now:
                    next_frame_at = now

        except Exception as error:
            self.error = error
            print(f"[LIVE STREAM] Erro na thread de captura: {error}")
            self._notify_frame_ready()

        finally:
            self.ready_event.set()

            if capture is not None:
                try:
                    capture.close()
                except Exception as error:
                    print(
                        "[LIVE STREAM] Erro ao liberar captura: "
                        f"{error}"
                    )

            self._notify_frame_ready()
