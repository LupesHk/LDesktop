import json

from core.paths import DATA_DIR


SHORTCUT_SETTINGS_FILE = DATA_DIR / "shortcut_settings.json"

DEFAULT_SHORTCUTS = {
    "capture": "f8",
    "replay": "f9",
}


def load_shortcuts():
    try:
        with SHORTCUT_SETTINGS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            data = {}
    except FileNotFoundError:
        data = {}
    except Exception as error:
        print(f"[SHORTCUTS] Erro ao ler configurações: {error}")
        data = {}

    capture = str(data.get("capture") or DEFAULT_SHORTCUTS["capture"]).strip().lower()
    replay = str(data.get("replay") or DEFAULT_SHORTCUTS["replay"]).strip().lower()

    if not capture or not replay or capture == replay:
        print("[SHORTCUTS] Configuração inválida; usando atalhos padrão.")
        return DEFAULT_SHORTCUTS.copy()

    return {"capture": capture, "replay": replay}


def save_shortcuts(capture, replay):
    capture = str(capture).strip().lower()
    replay = str(replay).strip().lower()

    if not capture or not replay:
        raise ValueError("Os dois atalhos precisam estar definidos.")
    if capture == replay:
        raise ValueError("Os atalhos de captura e replay não podem ser iguais.")

    settings = {"capture": capture, "replay": replay}
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temporary = SHORTCUT_SETTINGS_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=4)

    temporary.replace(SHORTCUT_SETTINGS_FILE)
    print(f"[SHORTCUTS] Salvos: captura={capture}, replay={replay}")
    return settings
