
import json
import re
import urllib.request
import urllib.error

from dataclasses import dataclass
from PySide6.QtCore import QThread, Signal

from core.update_config import (
    APP_VERSION,
    UPDATE_CHANNEL,
    GITHUB_REPOSITORY,
)


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
        "https://raw.githubusercontent.com/"
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
        manifest = json.loads(content.decode("utf-8"))
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

    if not isinstance(download_url, str) or not download_url.startswith("https://"):
        raise UpdateCheckError("URL de download não é segura.")

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
