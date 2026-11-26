import subprocess
import time
import shutil

from datetime import datetime

from PySide6.QtGui import QGuiApplication

from replay.audio_capture import AudioCapture
from replay.process_guard import ProcessGuard
from replay.library import ReplayLibrary, UNKNOWN_GAME
from replay.game_detector import GameDetector

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
        self.library = ReplayLibrary()
        self.game_detector = GameDetector()
        self.last_saved_game = UNKNOWN_GAME

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
        scale_factor = float(screen.devicePixelRatio() or 1.0)

        # No Windows, o Qt mant?m a posi??o do monitor
        # em coordenadas nativas; somente as dimens?es
        # precisam da convers?o pelo DPR.
        physical_x = geometry.x()
        physical_y = geometry.y()
        physical_width = round(geometry.width() * scale_factor)
        physical_height = round(geometry.height() * scale_factor)

        self.monitor = {
            "name": screen.name(),
            "x": physical_x,
            "y": physical_y,
            "width": physical_width,
            "height": physical_height,
            "logical_width": geometry.width(),
            "logical_height": geometry.height(),
            "scale_factor": scale_factor,
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
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW
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
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW
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
        print(
            f"Resolução lógica: "
            f"{monitor['logical_width']}x{monitor['logical_height']}"
        )
        print(f"Escala DPI: {monitor['scale_factor']}")
        print(f"Resolução física: {width}x{height}")
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

        # Identify the foreground game when F9 is requested.
        detected_game = UNKNOWN_GAME

        try:
            detection = self.game_detector.detect_active_game()
            detected_game = detection.get("game_name") or UNKNOWN_GAME

            window_info = detection.get("window_info") or {}

            print(
                f"[REPLAY LIBRARY] Active window: "
                f"{window_info.get('window_title') or 'Unknown'}"
            )
            print(
                f"[REPLAY LIBRARY] Process: "
                f"{window_info.get('process_name') or 'Unknown'}"
            )
            detection_source = detection.get("detection_source")
            if not detection_source and detection.get("profile"):
                detection_source = "Manual profile"
            detection_source = detection_source or "No match"

            print(
                f"[REPLAY LIBRARY] Identified game: {detected_game} "
                f"(source: {detection_source})"
            )

        except Exception as error:
            print(
                f"[REPLAY LIBRARY] Game detection failed: {error}"
            )

        self.last_saved_game = detected_game

        ffprobe = FFPROBE

        if not ffprobe.exists():
            raise FileNotFoundError(
                "FFprobe não encontrado."
            )

        SAVED_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        snapshot_dir = SAVED_DIR / f"snapshot_{timestamp}"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        segments = []

        for source in sorted(BUFFER_DIR.glob("segment_*.mp4")):
            snapshot = snapshot_dir / source.name

            try:
                before = source.stat()

                # Ignora segmentos muito recentes, possivelmente em gravação.
                if time.time() - before.st_mtime < 1.5:
                    continue

                shutil.copy2(source, snapshot)

                after = source.stat()

                # Descarta cópias feitas enquanto o FFmpeg alterava o arquivo.
                if (
                    before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                ):
                    snapshot.unlink(missing_ok=True)
                    continue

                result = subprocess.run(
                    [
                        str(FFPROBE),
                        "-v", "error",
                        "-show_entries", "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        str(snapshot)
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )

                if result.returncode != 0:
                    snapshot.unlink(missing_ok=True)
                    continue

                duration = float(result.stdout.strip())

                if 0.90 <= duration <= 1.10:
                    segments.append(snapshot)
                else:
                    snapshot.unlink(missing_ok=True)

            except (
                ValueError,
                subprocess.TimeoutExpired,
                OSError
            ):
                snapshot.unlink(missing_ok=True)
                continue

        segments.sort(
            key=lambda file: file.stat().st_mtime
        )

        segments = segments[-30:]

        if not segments:
            shutil.rmtree(snapshot_dir, ignore_errors=True)

            raise RuntimeError(
                "Nenhum segmento íntegro disponível para salvar."
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
                encoding="ascii",
                newline="\n"
            ) as file:

                for segment in segments:
                    relative_path = segment.relative_to(
                    SAVED_DIR
                    ).as_posix()

                    file.write(f"file '{relative_path}'\n")

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
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW
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
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Erro ao juntar áudio e vídeo: {result.stderr}"
                )

            print(f"[REPLAY] Vídeo salvo: {output}")
            replay_saved = True

            try:
                output = self.library.organize_replay(
                    output,
                    game_name=detected_game,
                )
            except Exception as error:
                print(
                    f"[REPLAY LIBRARY] Falha na organiza??o: {error}"
                )
                print(
                    f"[REPLAY LIBRARY] Arquivo mantido em: {output}"
                )

            return output

        finally:
            if replay_saved:
                shutil.rmtree(snapshot_dir, ignore_errors=True)
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
