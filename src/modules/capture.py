
from datetime import datetime
from pathlib import Path
from PIL import ImageGrab
from winotify import Notification
from modules.device import get_device_token
from core.service_config import API_BASE_URL

import requests
import os


BASE_DIR = Path(__file__).resolve().parents[2]
CAPTURE_DIR = BASE_DIR / "data" / "captures"


def capture_screen():
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
    filepath = CAPTURE_DIR / f"capture_{timestamp}.png"

    device_token = get_device_token()

    if not device_token:
        Notification(
            app_id="L Desktop",
            title="Dispositivo não vinculado",
            msg="Vincule sua conta Discord antes de capturar.",
            duration="short"
        ).show()

        return False
    try:
        screenshot = ImageGrab.grab()
        screenshot.save(filepath, "PNG")

    except Exception as error:
        print(f"[CAPTURE] Erro ao capturar: {error}")

        Notification(
            app_id="L Desktop",
            title="Erro na captura",
            msg="Não foi possível capturar a tela.",
            duration="short"
        ).show()

        return None

    try:
        with open(filepath, "rb") as image:
            response = requests.post(
                f"{API_BASE_URL}/capture",
                headers={
                    "x-device-token": device_token
                },
                files={
                    "image": ("captura.png", image, "image/png")
                },
                timeout=30
            )

        response.raise_for_status()

        filepath.unlink()

        Notification(
            app_id="L Desktop",
            title="Captura concluída",
            msg="Imagem enviada ao Discord com sucesso.",
            duration="short"
        ).show()

        print("[CAPTURE] Enviada ao Discord e removida localmente.")

        return True

    except Exception as error:
        print(f"[CAPTURE] Erro no envio: {error}")

        Notification(
            app_id="L Desktop",
            title="Falha no envio",
            msg="A captura foi salva, mas não chegou ao Discord.",
            duration="short"
        ).show()

        return False