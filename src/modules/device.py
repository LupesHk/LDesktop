
import json
import os
from pathlib import Path

APP_DIR = Path(os.getenv("APPDATA", Path.home())) / "LDesktop"
CONFIG_FILE = APP_DIR / "device.json"


def save_device_token(token):
    APP_DIR.mkdir(parents=True, exist_ok=True)

    with open(CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump({"device_token": token}, file)


def get_device_token():
    if not CONFIG_FILE.exists():
        return None

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        return data.get("device_token")

    except (OSError, json.JSONDecodeError):
        return None
