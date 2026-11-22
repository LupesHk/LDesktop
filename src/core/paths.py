
import os
import sys
from pathlib import Path


# Pasta principal do aplicativo
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parents[2]


# Dependências distribuídas junto ao aplicativo
BIN_DIR = APP_DIR / "bin"

FFMPEG = BIN_DIR / "ffmpeg.exe"
FFPROBE = BIN_DIR / "ffprobe.exe"


# Dados persistentes do usuário
APPDATA_DIR = Path(
    os.environ.get(
        "APPDATA",
        Path.home() / "AppData" / "Roaming"
    )
)

DATA_DIR = APPDATA_DIR / "LDesktop"

# Replay
REPLAY_DIR = DATA_DIR / "replay"
BUFFER_DIR = REPLAY_DIR / "buffer"
SAVED_DIR = REPLAY_DIR / "saved"

# Logs
LOG_DIR = DATA_DIR / "logs"
FFMPEG_LOG = LOG_DIR / "ffmpeg.log"


def ensure_data_dirs():
    """Cria as pastas necessárias para o funcionamento do aplicativo."""

    for directory in (
        BUFFER_DIR,
        SAVED_DIR,
        LOG_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
