
import hashlib
import hmac
import json
import os
import re
import urllib.request
import urllib.error

from pathlib import Path
from urllib.parse import urlparse
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from core.update_config import (
    APP_VERSION,
    UPDATE_CHANNEL,
    GITHUB_REPOSITORY,
)


MAX_PACKAGE_SIZE = 1024 * 1024 * 1024

ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    sha256: str
    notes: str = ""


class UpdateCheckError(Exception):
    pass


class UpdateWorker(QThread):

    update_available = Signal(object)
    check_failed = Signal(str)
    check_finished = Signal()

    def run(self):
        try:
            update = check_for_update()

            if update:
                self.update_available.emit(update)

        except Exception as error:
            self.check_failed.emit(str(error))

        finally:
            self.check_finished.emit()


class UpdateDownloadWorker(QThread):

    progress = Signal(int)
    download_ready = Signal(str)
    download_failed = Signal(str)

    def __init__(self, update, parent=None):
        super().__init__(parent)
        self.update = update

    def run(self):
        try:
            path = download_update(
                self.update,
                progress_callback=self.progress.emit,
                stop_requested=self.isInterruptionRequested
            )

            self.download_ready.emit(str(path))

        except Exception as error:
            self.download_failed.emit(str(error))


def parse_version(version):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)

    if not match:
        raise ValueError(f"Versão inválida: {version}")

    return tuple(map(int, match.groups()))


def check_for_update():

    if not GITHUB_REPOSITORY:
        return None

    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
        GITHUB_REPOSITORY
    ):
        raise UpdateCheckError("Repositório GitHub inválido.")

    if UPDATE_CHANNEL not in ("stable", "beta", "development"):
        raise UpdateCheckError("Canal de atualização inválido.")

    manifest_url = (
        f"https://raw.githubusercontent.com/"
        f"{GITHUB_REPOSITORY}/main/"
        f"updates/{UPDATE_CHANNEL}.json"
    )

    request = urllib.request.Request(
        manifest_url,
        headers={
            "User-Agent": "LDesktop-Updater/1.0",
            "Accept": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            if response.status != 200:
                raise UpdateCheckError(
                    f"Servidor respondeu com status {response.status}."
                )

            content = response.read(64 * 1024)

    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise UpdateCheckError(
            f"Não foi possível consultar atualizações: {error}"
        ) from error

    try:
        manifest = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpdateCheckError(
            "Manifesto de atualização inválido."
        ) from error

    try:
        remote_version = manifest["version"]
        download_url = manifest["download_url"]
        sha256 = manifest["sha256"]
        notes = manifest.get("notes", "")

        current = parse_version(APP_VERSION)
        remote = parse_version(remote_version)

    except (KeyError, TypeError, ValueError) as error:
        raise UpdateCheckError(
            f"Dados incompletos no manifesto: {error}"
        ) from error

    parsed_url = urlparse(download_url) if isinstance(
        download_url, str
    ) else None

    if (
        not parsed_url
        or parsed_url.scheme != "https"
        or parsed_url.hostname != "github.com"
    ):
        raise UpdateCheckError(
            "O download precisa vir de um GitHub Release HTTPS."
        )

    if not isinstance(sha256, str) or not re.fullmatch(
        r"[a-fA-F0-9]{64}", sha256
    ):
        raise UpdateCheckError("Hash SHA-256 inválido.")

    if not isinstance(notes, str):
        notes = ""

    if remote <= current:
        return None

    return UpdateInfo(
        version=remote_version,
        download_url=download_url,
        sha256=sha256.lower(),
        notes=notes,
    )


def download_update(
    update,
    progress_callback=None,
    stop_requested=None
):
    """Baixa o instalador e valida seu SHA-256."""

    parsed = urlparse(update.download_url)

    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
    ):
        raise UpdateCheckError("URL de download não permitida.")

    local_appdata = Path(
        os.environ.get(
            "LOCALAPPDATA",
            Path.home() / "AppData" / "Local"
        )
    )

    update_dir = local_appdata / "LDesktop" / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)

    filename = f"LDesktop-Setup-{update.version}.exe"

    final_path = update_dir / filename
    partial_path = update_dir / f"{filename}.part"

    request = urllib.request.Request(
        update.download_url,
        headers={
            "User-Agent": "LDesktop-Updater/1.0",
            "Accept": "application/octet-stream",
        }
    )

    digest = hashlib.sha256()
    downloaded = 0

    try:
        with urllib.request.urlopen(request, timeout=20) as response:

            final_url = urlparse(response.geturl())

            if (
                final_url.scheme != "https"
                or final_url.hostname not in ALLOWED_DOWNLOAD_HOSTS
            ):
                raise UpdateCheckError(
                    "O servidor redirecionou para um endereço não permitido."
                )

            content_length = response.headers.get("Content-Length")

            try:
                total_size = (
                    int(content_length)
                    if content_length else 0
                )
            except ValueError:
                total_size = 0

            if total_size > MAX_PACKAGE_SIZE:
                raise UpdateCheckError(
                    "O pacote excede o limite de tamanho permitido."
                )

            with open(partial_path, "wb") as file:

                while True:

                    if stop_requested and stop_requested():
                        raise InterruptedError(
                            "Download cancelado."
                        )

                    chunk = response.read(1024 * 1024)

                    if not chunk:
                        break

                    downloaded += len(chunk)

                    if downloaded > MAX_PACKAGE_SIZE:
                        raise UpdateCheckError(
                            "O pacote excede o limite de tamanho permitido."
                        )

                    digest.update(chunk)
                    file.write(chunk)

                    if total_size > 0 and progress_callback:
                        percentage = min(
                            99,
                            int(downloaded * 100 / total_size)
                        )
                        progress_callback(percentage)

        if total_size and downloaded != total_size:
            raise UpdateCheckError(
                "O download foi interrompido antes de terminar."
            )

        calculated_hash = digest.hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            update.sha256.lower()
        ):
            raise UpdateCheckError(
                "A verificação SHA-256 falhou. "
                "O pacote foi rejeitado."
            )

        os.replace(partial_path, final_path)

        if progress_callback:
            progress_callback(100)

        return final_path

    except Exception:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass

        raise
