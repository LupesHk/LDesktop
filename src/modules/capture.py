
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

import requests
from PIL import ImageGrab
from PySide6.QtCore import QThread, Signal
from winotify import Notification

from modules.device import get_device_token
from core.service_config import API_BASE_URL
from core.paths import DATA_DIR, FFMPEG


CAPTURE_DIR = DATA_DIR / "captures"
REPLAY_QUEUE_DIR = DATA_DIR / "replay_uploads"

MAX_QUEUE_BYTES = 1024 ** 3  # 1 GB
MAX_UPLOAD_BYTES = 18 * 1024 * 1024  # 18 MiB

RETRY_INTERVALS = (15, 30, 60, 120, 300)
REQUEST_TIMEOUT = (10, 180)

CAPTURE_PATTERN = re.compile(
    r"^capture_([a-f0-9]{32})$",
    re.IGNORECASE
)

REPLAY_PATTERN = re.compile(
    r"^replay_([a-f0-9]{32})$",
    re.IGNORECASE
)

def ensure_queue_dirs():
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    REPLAY_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

def notify(title, message):
    try:
        Notification(
            app_id="L Desktop",
            title=title,
            msg=message,
            duration="short"
        ).show()
    except Exception as error:
        print(f"[QUEUE] Erro na notificação: {error}")


def prepare_capture_queue():
    ensure_queue_dirs()

    # Remove arquivos temporários deixados por encerramentos abruptos.
    for folder in (CAPTURE_DIR, REPLAY_QUEUE_DIR):
        for temporary in folder.glob("*.tmp"):
            try:
                temporary.unlink(missing_ok=True)
            except OSError as error:
                print(
                    f"[QUEUE] Não foi possível limpar "
                    f"{temporary.name}: {error}"
                )

    # Recupera capturas antigas sem identificador padronizado.
    for filepath in CAPTURE_DIR.glob("*.png"):
        if not CAPTURE_PATTERN.fullmatch(filepath.stem):
            new_path = CAPTURE_DIR / f"capture_{uuid4().hex}.png"

            try:
                filepath.rename(new_path)
                print(f"[QUEUE] Captura recuperada: {new_path.name}")
            except OSError as error:
                print(f"[QUEUE] Erro ao recuperar captura: {error}")

    # Recupera replays antigos sem identificador padronizado.
    for filepath in REPLAY_QUEUE_DIR.glob("*.mp4"):
        if not REPLAY_PATTERN.fullmatch(filepath.stem):
            new_path = REPLAY_QUEUE_DIR / f"replay_{uuid4().hex}.mp4"

            try:
                filepath.rename(new_path)
                print(f"[QUEUE] Replay recuperado: {new_path.name}")
            except OSError as error:
                print(f"[QUEUE] Erro ao recuperar replay: {error}")


def queue_size():
    total = 0

    for folder, pattern in (
        (CAPTURE_DIR, "*.png"),
        (REPLAY_QUEUE_DIR, "*.mp4")
    ):
        for filepath in folder.glob(pattern):
            try:
                total += filepath.stat().st_size
            except OSError:
                pass

    return total


def capture_screen():
    try:
        ensure_queue_dirs()

        if not get_device_token():
            notify(
                "Dispositivo não vinculado",
                "Vincule sua conta Discord antes de capturar."
            )
            return False

        if queue_size() >= MAX_QUEUE_BYTES:
            notify(
                "Fila cheia",
                "A fila atingiu 1 GB. Libere espaço antes de novas capturas."
            )
            return False

        capture_id = uuid4().hex

        filepath = CAPTURE_DIR / f"capture_{capture_id}.png"
        temporary = CAPTURE_DIR / f"capture_{capture_id}.png.tmp"

        screenshot = ImageGrab.grab()
        screenshot.save(temporary, format="PNG")
        temporary.replace(filepath)

        print(f"[CAPTURE] Salva na fila: {filepath.name}")

        return True

    except Exception as error:
        print(f"[CAPTURE] Erro ao capturar: {error}")

        notify(
            "Erro na captura",
            "Não foi possível salvar a captura."
        )

        return False


def queue_replay(source):
    """Copia o replay salvo para a fila sem alterar o original."""
    try:
        source = Path(source)

        if not source.is_file():
            raise FileNotFoundError(
                f"Replay não encontrado: {source}"
            )

        if source.suffix.lower() != ".mp4":
            raise ValueError("O arquivo do replay precisa ser MP4.")

        ensure_queue_dirs()

        if not get_device_token():
            notify(
                "Dispositivo não vinculado",
                "O replay foi salvo no computador, mas não entrou na fila."
            )
            return False

        size = source.stat().st_size

        if queue_size() + size > MAX_QUEUE_BYTES:
            notify(
                "Fila cheia",
                "Não há espaço suficiente para adicionar este replay."
            )
            print("[REPLAY QUEUE] Limite de 1 GB atingido.")
            return False

        replay_id = uuid4().hex

        destination = (
            REPLAY_QUEUE_DIR / f"replay_{replay_id}.mp4"
        )

        temporary = (
            REPLAY_QUEUE_DIR / f"replay_{replay_id}.mp4.tmp"
        )

        shutil.copy2(source, temporary)
        temporary.replace(destination)

        print(
            f"[REPLAY QUEUE] Adicionado: {destination.name} "
            f"({size / 1024 / 1024:.2f} MiB)"
        )

        notify(
            "Replay na fila",
            "O replay foi salvo e será enviado ao Discord."
        )

        return True

    except Exception as error:
        print(f"[REPLAY QUEUE] Erro ao adicionar: {error}")

        notify(
            "Erro ao preparar replay",
            "O replay continua salvo no computador."
        )

        return False


class CaptureQueueWorker(QThread):
    status = Signal(str)
    pending_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_event = threading.Event()
        self._last_pending_count = -1

    def stop(self):
        self._stop_event.set()

    def pending_files(self):
        files = []

        for filepath in CAPTURE_DIR.glob("capture_*.png"):
            if CAPTURE_PATTERN.fullmatch(filepath.stem):
                files.append(filepath)

        for filepath in REPLAY_QUEUE_DIR.glob("replay_*.mp4"):
            if REPLAY_PATTERN.fullmatch(filepath.stem):
                files.append(filepath)

        def sort_key(item):
            try:
                return item.stat().st_mtime_ns, item.name
            except OSError:
                return 0, item.name

        return sorted(files, key=sort_key)

    def prepare_replay_upload(self, filepath, replay_id):
        """Retorna o original ou uma cópia comprimida para o Discord."""
        original_size = filepath.stat().st_size

        if original_size <= MAX_UPLOAD_BYTES:
            return filepath, False

        if not FFMPEG.is_file():
            raise FileNotFoundError(
                f"FFmpeg não encontrado: {FFMPEG}"
            )

        prepared = (
            REPLAY_QUEUE_DIR / f"prepared_{replay_id}.mp4"
        )

        # Reduz gradualmente a taxa de bits até caber no limite.
        encoding_profiles = (
            ("3500k", "4000k", "8000k"),
            ("2800k", "3200k", "6400k"),
            ("2200k", "2600k", "5200k")
        )

        for bitrate, maxrate, bufsize in encoding_profiles:
            prepared.unlink(missing_ok=True)

            command = [
                str(FFMPEG),
                "-hide_banner",
                "-loglevel", "error",
                "-y",

                "-i", str(filepath),

                "-map", "0:v:0",
                "-map", "0:a:0?",

                "-c:v", "libx264",
                "-preset", "veryfast",
                "-b:v", bitrate,
                "-maxrate", maxrate,
                "-bufsize", bufsize,
                "-pix_fmt", "yuv420p",

                "-c:a", "aac",
                "-b:a", "128k",

                "-movflags", "+faststart",
                str(prepared)
            ]

            print(
                f"[REPLAY QUEUE] Comprimindo para envio: "
                f"vídeo {bitrate}"
            )

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=240,
                creationflags=getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0
                )
            )

            if result.returncode != 0:
                print(
                    f"[REPLAY QUEUE] FFmpeg: {result.stderr[-1500:]}"
                )
                continue

            if not prepared.is_file():
                continue

            prepared_size = prepared.stat().st_size

            print(
                f"[REPLAY QUEUE] Cópia comprimida: "
                f"{prepared_size / 1024 / 1024:.2f} MiB"
            )

            if prepared_size <= MAX_UPLOAD_BYTES:
                return prepared, True

        prepared.unlink(missing_ok=True)

        raise RuntimeError(
            "Não foi possível reduzir o replay para menos de 18 MiB."
        )

    def send_file(self, filepath):
        device_token = get_device_token()

        if not device_token:
            raise RuntimeError("Dispositivo ainda não vinculado.")

        capture_match = CAPTURE_PATTERN.fullmatch(filepath.stem)
        replay_match = REPLAY_PATTERN.fullmatch(filepath.stem)

        if capture_match:
            file_id = capture_match.group(1)
            endpoint = "/capture"
            header_name = "x-capture-id"
            field_name = "image"
            upload_name = "captura.png"
            content_type = "image/png"
            upload_path = filepath
            temporary_upload = False

        elif replay_match:
            file_id = replay_match.group(1)
            endpoint = "/replay"
            header_name = "x-replay-id"
            field_name = "video"
            upload_name = "replay.mp4"
            content_type = "video/mp4"

            upload_path, temporary_upload = (
                self.prepare_replay_upload(filepath, file_id)
            )

        else:
            raise RuntimeError("Arquivo de fila com nome inválido.")

        try:
            with upload_path.open("rb") as file:
                response = requests.post(
                    f"{API_BASE_URL}{endpoint}",
                    headers={
                        "x-device-token": device_token,
                        header_name: file_id
                    },
                    files={
                        field_name: (
                            upload_name,
                            file,
                            content_type
                        )
                    },
                    timeout=REQUEST_TIMEOUT
                )

            response.raise_for_status()

            data = response.json()

            if data.get("success") is not True:
                raise RuntimeError(
                    data.get("error", "Servidor não confirmou o envio.")
                )

        finally:
            if (
                filepath.suffix.lower() == ".mp4"
                and temporary_upload
            ):
                upload_path.unlink(missing_ok=True)

    def run(self):
        print("[QUEUE] Worker de envios iniciado.")

        try:
            prepare_capture_queue()
        except Exception as error:
            self.status.emit(
                f"[QUEUE] Erro ao recuperar arquivos: {error}"
            )
            return

        failures = 0
        retry_at = 0
        failure_notified = False

        while not self._stop_event.is_set():
            try:
                files = self.pending_files()
            except OSError as error:
                self.status.emit(
                    f"[QUEUE] Erro ao ler a fila: {error}"
                )
                self._stop_event.wait(5)
                continue

            pending = len(files)

            if pending != self._last_pending_count:
                self._last_pending_count = pending
                self.pending_changed.emit(pending)

            if not files:
                failures = 0
                retry_at = 0
                failure_notified = False
                self._stop_event.wait(2)
                continue

            remaining = retry_at - time.monotonic()

            if remaining > 0:
                self._stop_event.wait(min(remaining, 1))
                continue

            filepath = files[0]
            is_replay = filepath.suffix.lower() == ".mp4"

            try:
                self.send_file(filepath)
                filepath.unlink(missing_ok=True)

                if is_replay:
                    self.status.emit(
                        f"[QUEUE] Replay enviado: {filepath.name}"
                    )
                    notify(
                        "Replay enviado",
                        "O vídeo foi enviado ao Discord com sucesso."
                    )
                else:
                    self.status.emit(
                        f"[QUEUE] Captura enviada: {filepath.name}"
                    )
                    notify(
                        "Captura concluída",
                        "Imagem enviada ao Discord com sucesso."
                    )

                failures = 0
                retry_at = 0
                failure_notified = False

            except Exception as error:
                delay = RETRY_INTERVALS[
                    min(failures, len(RETRY_INTERVALS) - 1)
                ]

                failures += 1
                retry_at = time.monotonic() + delay

                self.status.emit(
                    f"[QUEUE] Falha no envio de {filepath.name}: "
                    f"{error}. Nova tentativa em {delay}s."
                )

                if not failure_notified:
                    notify(
                        "Arquivo aguardando envio",
                        "O arquivo foi preservado. O L Desktop tentará novamente."
                    )
                    failure_notified = True

        print("[QUEUE] Worker de envios encerrado.")
