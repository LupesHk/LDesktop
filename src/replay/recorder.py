import subprocess
import time

from datetime import datetime

from PySide6.QtGui import QGuiApplication

from replay.audio_capture import AudioCapture
from replay.process_guard import ProcessGuard

from core.paths import (
    FFMPEG,
    FFPROBE,
    BUFFER_DIR,
    SAVED_DIR,
    FFMPEG_LOG,
    ensure_data_dirs,
)


FPS = 30
SEGMENT_DURATION = 1
BUFFER_SECONDS = 30
BITRATE = "6M"

class ReplayRecorder:

    def __init__(self):
        self.process = None
        self.log_file = None
        self.encoder = None
        self.monitor = None
        self.audio_capture = AudioCapture()
        self.process_guard = None

    def detect_monitor(self):
        app = QGuiApplication.instance()

        if app is None:
            raise RuntimeError(
                "A aplicação Qt precisa estar inicializada."
            )

        screen = QGuiApplication.primaryScreen()

        if screen is None:
            raise RuntimeError("Monitor principal não encontrado.")

        geometry = screen.geometry()

        self.monitor = {
            "name": screen.name(),
            "x": geometry.x(),
            "y": geometry.y(),
            "width": geometry.width(),
            "height": geometry.height()
        }

        return self.monitor

    def encoder_options(self, encoder):

        if encoder == "h264_amf":
            return ["-quality", "speed"]

        if encoder == "h264_nvenc":
            return ["-preset", "p1"]

        if encoder == "h264_qsv":
            return ["-preset", "veryfast"]

        if encoder == "libx264":
            return [
                "-preset", "ultrafast",
                "-tune", "zerolatency"
            ]

        return []

    def test_encoder(self, encoder):

        command = [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", "testsrc2=size=640x360:rate=30",
            "-frames:v", "30",
            "-c:v", encoder,
            *self.encoder_options(encoder),
            "-pix_fmt", "yuv420p",
            "-f", "null",
            "-"
        ]

        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=15
            )

            return result.returncode == 0

        except (subprocess.TimeoutExpired, OSError):
            return False

    def detect_encoder(self):

        if not FFMPEG.exists():
            raise FileNotFoundError(
                f"FFmpeg não encontrado: {FFMPEG}"
            )

        result = subprocess.run(
            [str(FFMPEG), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=15
        )

        available = result.stdout

        candidates = [
            "h264_amf",
            "h264_nvenc",
            "h264_qsv",
            "libx264"
        ]

        for encoder in candidates:

            if encoder not in available:
                continue

            print(f"Testando codificador: {encoder}")

            if self.test_encoder(encoder):
                self.encoder = encoder

                print(
                    f"Codificador selecionado: {encoder}"
                )

                return encoder

        raise RuntimeError(
            "Nenhum codificador H.264 funcional foi encontrado."
        )

    def start(self):

        if self.process and self.process.poll() is None:
            print("Replay Buffer já está ativo.")
            return False

        monitor = self.detect_monitor()
        encoder = self.detect_encoder()

        ensure_data_dirs()

        for file in BUFFER_DIR.glob("segment_*.mp4"):
            file.unlink()

        width = monitor["width"]
        height = monitor["height"]

        width -= width % 2
        height -= height % 2

        # Inicia captura de áudio
        self.audio_capture.start()

        command = [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel", "warning",

            "-f", "gdigrab",
            "-framerate", str(FPS),
            "-draw_mouse", "1",
            "-offset_x", str(monitor["x"]),
            "-offset_y", str(monitor["y"]),
            "-video_size", f"{width}x{height}",
            "-i", "desktop",

            "-an",
            "-c:v", encoder,
            *self.encoder_options(encoder),
            "-b:v", BITRATE,
            "-pix_fmt", "yuv420p",
            "-g", str(FPS),
            "-forced_idr", "1",
            "-force_key_frames",
            "expr:gte(t,n_forced*1)",

            "-f", "segment",
            "-segment_time", str(SEGMENT_DURATION),
            "-segment_time_delta", "0.05",
            "-segment_wrap", str(BUFFER_SECONDS + 1),
            "-segment_start_number", "0",
            "-reset_timestamps", "1",
            "-segment_format", "mp4",

            str(BUFFER_DIR / "segment_%03d.mp4")
        ]

        log_path = FFMPEG_LOG

        self.log_file = open(
            log_path,
            "a",
            encoding="utf-8"
        )

        try:
            # Cria a proteção de processos do Windows
            self.process_guard = ProcessGuard()

            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self.log_file,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            # Vincula o FFmpeg ao controlador
            self.process_guard.assign(self.process)

            time.sleep(2)

            if self.process.poll() is not None:
                raise RuntimeError(
                    "FFmpeg encerrou inesperadamente. "
                    "Consulte data/replay/ffmpeg.log."
                )

        except Exception:
            self.stop()
            raise

        print("Replay Buffer iniciado.")
        print(f"Monitor: {monitor['name']}")
        print(f"Resolução: {width}x{height}")
        print(f"Codificador: {encoder}")

        return True


    def stop(self):
        process = self.process

        try:
            if process and process.poll() is None:
                try:
                    if process.stdin:
                        process.stdin.write(b"q\n")
                        process.stdin.flush()

                    process.wait(timeout=10)

                except (subprocess.TimeoutExpired, OSError):
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except (OSError, subprocess.TimeoutExpired):
                        pass

        finally:
            self.process = None

            try:
                self.audio_capture.stop()
            finally:
                if self.process_guard:
                    self.process_guard.close()
                    self.process_guard = None

                if self.log_file:
                    self.log_file.close()
                    self.log_file = None

        print("Replay Buffer encerrado.")


    def is_running(self):

        return (
            self.process is not None
            and self.process.poll() is None
        )

    def save_replay(self):

        if not self.is_running():
            raise RuntimeError(
                "Replay Buffer não está ativo."
            )

        ffprobe = FFPROBE

        if not ffprobe.exists():
            raise FileNotFoundError(
                "FFprobe não encontrado."
            )

        SAVED_DIR.mkdir(parents=True, exist_ok=True)

        valid_segments = []

        for segment in BUFFER_DIR.glob("segment_*.mp4"):

            try:
                result = subprocess.run(
                    [
                        str(ffprobe),
                        "-v", "error",
                        "-show_entries", "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        str(segment)
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode != 0:
                    continue

                duration = float(result.stdout.strip())

                if 0.90 <= duration <= 1.10:
                    valid_segments.append(segment)

            except (
                ValueError,
                subprocess.TimeoutExpired,
                OSError
            ):
                continue

        valid_segments.sort(
            key=lambda file: file.stat().st_mtime
        )

        segments = valid_segments[-30:]

        if not segments:
            raise RuntimeError(
                "Nenhum segmento de vídeo disponível para salvar."
            )

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        output = SAVED_DIR / f"replay_{timestamp}.mp4"
        video_only = SAVED_DIR / f"video_{timestamp}.mp4"
        audio_file = SAVED_DIR / f"audio_{timestamp}.wav"
        list_file = SAVED_DIR / f"concat_{timestamp}.txt"

        # Estima o instante final do último segmento de vídeo
        last_segment_time = segments[-1].stat().st_mtime

        replay_end_time = (
            time.monotonic()
            - (time.time() - last_segment_time)
        )

        replay_saved = False

        try:

            # Prepara a lista de vídeos
            with open(
                list_file,
                "w",
                encoding="utf-8"
            ) as file:

                for segment in segments:
                    path = segment.resolve().as_posix()
                    file.write(f"file '{path}'\n")

            # Junta os segmentos de vídeo
            concat_command = [
                str(FFMPEG),
                "-hide_banner",
                "-loglevel", "error",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                "-movflags", "+faststart",
                str(video_only)
            ]

            result = subprocess.run(
                concat_command,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Erro ao montar vídeo: {result.stderr}"
                )

            # Extrai os últimos 30 segundos de áudio
            self.audio_capture.save_wav(
                audio_file,
                duration=30,
                end_time=replay_end_time
            )

            # Junta vídeo e áudio no MP4 final
            mux_command = [
                str(FFMPEG),
                "-hide_banner",
                "-loglevel", "error",
                "-y",

                "-i", str(video_only),
                "-i", str(audio_file),

                "-map", "0:v:0",
                "-map", "1:a:0",

                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",

                "-shortest",
                "-movflags", "+faststart",

                str(output)
            ]

            result = subprocess.run(
                mux_command,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Erro ao juntar áudio e vídeo: {result.stderr}"
                )

            print(f"[REPLAY] Vídeo salvo: {output}")
            replay_saved = True

            return output

        finally:
            if replay_saved:
                for temp_file in (video_only, audio_file, list_file):
                    try:
                        temp_file.unlink(missing_ok=True)
                    except OSError as error:
                        print(
                            f"[REPLAY] Não foi possível remover "
                            f"{temp_file.name}: {error}"
                        )
            else:
                print("[REPLAY] Arquivos temporários preservados para diagnóstico.")
