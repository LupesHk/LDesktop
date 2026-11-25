import json

from core.paths import DATA_DIR


LIVE_SETTINGS_FILE = DATA_DIR / "live_settings.json"

DEFAULT_SETTINGS = {
    "fps": 15,
    "quality": "Equilibrada",
    "source_type": "window",
    "window_title": "",
    "process_name": "",
    "monitor_id": "",
}

FPS_OPTIONS = (15, 30, 60)

QUALITY_BITRATES = {
    "Econômica": 1_500_000,
    "Equilibrada": 4_000_000,
    "Alta": 6_000_000,
}


def load_live_settings():
    try:
        with LIVE_SETTINGS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            data = {}
    except FileNotFoundError:
        data = {}
    except Exception as error:
        print(f"[LIVE CONFIG] Erro ao ler preferências: {error}")
        data = {}

    try:
        fps = int(data.get("fps", 15))
    except (TypeError, ValueError):
        fps = 15

    quality = data.get("quality", "Equilibrada")
    source_type = data.get("source_type", "window")

    if fps not in FPS_OPTIONS:
        fps = 15
    if quality not in QUALITY_BITRATES:
        quality = "Equilibrada"
    if source_type not in ("window", "monitor"):
        source_type = "window"

    return {
        "fps": fps,
        "quality": quality,
        "source_type": source_type,
        "window_title": str(data.get("window_title") or ""),
        "process_name": str(data.get("process_name") or ""),
        "monitor_id": str(data.get("monitor_id") or ""),
    }


def save_live_settings(
    fps,
    quality,
    capture_type="window",
    window_info=None,
    monitor_info=None,
):
    fps = int(fps)

    if fps not in FPS_OPTIONS:
        raise ValueError("FPS inválido.")
    if quality not in QUALITY_BITRATES:
        raise ValueError("Qualidade inválida.")
    if capture_type not in ("window", "monitor"):
        raise ValueError("Fonte de captura inválida.")

    window_info = window_info or {}
    monitor_info = monitor_info or {}

    settings = {
        "fps": fps,
        "quality": quality,
        "source_type": capture_type,
        "window_title": (
            str(window_info.get("title") or "")
            if capture_type == "window" else ""
        ),
        "process_name": (
            str(window_info.get("process_name") or "")
            if capture_type == "window" else ""
        ),
        "monitor_id": (
            str(monitor_info.get("id") or "")
            if capture_type == "monitor" else ""
        ),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary_file = LIVE_SETTINGS_FILE.with_suffix(".json.tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=4)

    temporary_file.replace(LIVE_SETTINGS_FILE)

    source_label = (
        settings["monitor_id"]
        if capture_type == "monitor"
        else settings["window_title"] or "janela"
    )

    print(
        f"[LIVE CONFIG] Salvo: {fps} FPS, {quality}, "
        f"fonte={capture_type}, {source_label}"
    )

    return settings
