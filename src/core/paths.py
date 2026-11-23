
import os
import sys
from pathlib import Path


# Diretório do aplicativo
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(sys._MEIPASS).resolve()
else:
    APP_DIR = Path(__file__).resolve().parents[2]
    RESOURCE_DIR = APP_DIR


# Dependências distribuídas junto ao aplicativo
BIN_DIR = RESOURCE_DIR / "bin"

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

# Recursos visuais
ASSETS_DIR = RESOURCE_DIR / "assets"
ICON = ASSETS_DIR / "icon.png"

def ensure_data_dirs():
    for directory in (
        BUFFER_DIR,
        SAVED_DIR,
        LOG_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
