import os
import sys
from pathlib import Path


REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_VALUE = "LDesktop"

PREFERENCE_REGISTRY_PATH = r"Software\LupesHk\LDesktop"
REGISTRY_INITIALIZED_VALUE = "StartupPreferenceInitialized"


def _startup_command():
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        return f'"{executable}" --background'

    executable = Path(sys.executable).resolve()
    project_root = Path(__file__).resolve().parents[2]
    script = project_root / "src" / "main.py"

    if not script.is_file():
        raise FileNotFoundError(
            f"Arquivo principal n?o encontrado: {script}"
        )

    return f'"{executable}" "{script}" --background'


def is_windows_startup_enabled():
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_PATH,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            command, value_type = winreg.QueryValueEx(
                key,
                REGISTRY_VALUE,
            )

        return (
            value_type == winreg.REG_SZ
            and isinstance(command, str)
            and "--background" in command
        )

    except FileNotFoundError:
        return False


def set_windows_startup(enabled):
    import winreg

    if enabled:
        command = _startup_command()

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                REGISTRY_VALUE,
                0,
                winreg.REG_SZ,
                command,
            )

        return

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            REGISTRY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, REGISTRY_VALUE)

    except FileNotFoundError:
        pass


def ensure_default_windows_startup():
    """Ativa a inicializa??o apenas na primeira execu??o instalada."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False

    local_appdata = Path(
        os.environ.get(
            "LOCALAPPDATA",
            Path.home() / "AppData" / "Local",
        )
    )

    expected_executable = (
        local_appdata / "Programs" / "LDesktop" / "LDesktop.exe"
    ).resolve()

    current_executable = Path(sys.executable).resolve()

    # N?o cadastrar builds port?teis ou execut?veis de teste.
    if current_executable != expected_executable:
        return False

    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        PREFERENCE_REGISTRY_PATH,
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        try:
            initialized, value_type = winreg.QueryValueEx(
                key,
                REGISTRY_INITIALIZED_VALUE,
            )
        except FileNotFoundError:
            initialized = 0
            value_type = None

        if value_type == winreg.REG_DWORD and initialized == 1:
            return False

        set_windows_startup(True)

        winreg.SetValueEx(
            key,
            REGISTRY_INITIALIZED_VALUE,
            0,
            winreg.REG_DWORD,
            1,
        )

    return True
