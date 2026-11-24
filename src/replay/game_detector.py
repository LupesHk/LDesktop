import ctypes
import json
import os

from pathlib import Path
from ctypes import wintypes

from core.paths import REPLAY_DIR
from replay.library import UNKNOWN_GAME


DEFAULT_PROFILES = [
    {
        "game_name": "Minecraft",
        "executable": "javaw.exe",
        "title_contains": ["minecraft"],
    },
    {
        "game_name": "Minecraft",
        "executable": "Minecraft.Windows.exe",
        "title_contains": [],
    },
    {
        "game_name": "Counter-Strike 2",
        "executable": "cs2.exe",
        "title_contains": [],
    },
    {
        "game_name": "Valorant",
        "executable": "VALORANT-Win64-Shipping.exe",
        "title_contains": [],
    },
    {
        "game_name": "Fortnite",
        "executable": "FortniteClient-Win64-Shipping.exe",
        "title_contains": [],
    },
    {
        "game_name": "Apex Legends",
        "executable": "r5apex.exe",
        "title_contains": [],
    },
    {
        "game_name": "Roblox",
        "executable": "RobloxPlayerBeta.exe",
        "title_contains": [],
    },
]


class GameDetector:

    def __init__(self, profiles_path=None):
        self.profiles_path = Path(
            profiles_path
            if profiles_path is not None
            else REPLAY_DIR / "game_profiles.json"
        )

        self.profiles_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.profiles = []
        self.load_profiles()

    def load_profiles(self):
        if not self.profiles_path.exists():
            self.profiles = [
                dict(profile)
                for profile in DEFAULT_PROFILES
            ]
            self.save_profiles()
            return

        try:
            data = json.loads(
                self.profiles_path.read_text(encoding="utf-8")
            )

            profiles = data.get("profiles", [])

            if not isinstance(profiles, list):
                raise ValueError("A lista de perfis é inválida.")

            self.profiles = profiles
            self._validate_profiles()

        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise RuntimeError(
                f"Não foi possível carregar os perfis de jogos: {error}"
            ) from error

    def _validate_profiles(self):
        for profile in self.profiles:
            if not isinstance(profile, dict):
                raise ValueError("Perfil de jogo inválido.")

            if not profile.get("game_name"):
                raise ValueError("Perfil sem nome de jogo.")

            if not profile.get("executable"):
                raise ValueError("Perfil sem executável.")

            if not isinstance(profile.get("title_contains", []), list):
                raise ValueError("title_contains precisa ser uma lista.")

    def save_profiles(self):
        data = {
            "version": 1,
            "profiles": self.profiles,
        }

        temporary = self.profiles_path.with_suffix(".json.tmp")

        temporary.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=4,
            ),
            encoding="utf-8",
        )

        temporary.replace(self.profiles_path)

    def list_profiles(self):
        return [
            dict(profile)
            for profile in self.profiles
        ]

    def add_profile(
        self,
        game_name,
        executable,
        title_contains=None,
    ):
        game_name = str(game_name).strip()
        executable = Path(str(executable).strip()).name

        if not game_name:
            raise ValueError("Informe o nome do jogo.")

        if not executable or not executable.lower().endswith(".exe"):
            raise ValueError("Informe um executável .exe válido.")

        if isinstance(title_contains, str):
            title_contains = [title_contains]

        title_contains = [
            str(value).strip()
            for value in (title_contains or [])
            if str(value).strip()
        ]

        profile = {
            "game_name": game_name,
            "executable": executable,
            "title_contains": title_contains,
        }

        for index, existing in enumerate(self.profiles):
            same_executable = (
                existing["executable"].casefold()
                == executable.casefold()
            )

            same_title_filter = [
                value.casefold()
                for value in existing.get("title_contains", [])
            ] == [
                value.casefold()
                for value in title_contains
            ]

            if same_executable and same_title_filter:
                self.profiles[index] = profile
                self.save_profiles()
                return profile

        self.profiles.append(profile)
        self.save_profiles()

        return profile

    def get_active_window_info(self):
        if os.name != "nt":
            raise OSError(
                "A identificação de janelas está disponível no Windows."
            )

        user32 = ctypes.WinDLL(
            "user32",
            use_last_error=True,
        )

        kernel32 = ctypes.WinDLL(
            "kernel32",
            use_last_error=True,
        )

        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE

        kernel32.CloseHandle.argtypes = [
            wintypes.HANDLE,
        ]
        kernel32.CloseHandle.restype = wintypes.BOOL

        user32.GetForegroundWindow.restype = wintypes.HWND

        user32.GetWindowTextLengthW.argtypes = [
            wintypes.HWND,
        ]
        user32.GetWindowTextLengthW.restype = ctypes.c_int

        user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int

        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        hwnd = user32.GetForegroundWindow()

        if not hwnd:
            return None

        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(
            max(title_length + 1, 2)
        )

        user32.GetWindowTextW(
            hwnd,
            title_buffer,
            len(title_buffer),
        )

        process_id = wintypes.DWORD()

        user32.GetWindowThreadProcessId(
            hwnd,
            ctypes.byref(process_id),
        )

        process_path = None
        process_handle = kernel32.OpenProcess(
            0x1000,  # PROCESS_QUERY_LIMITED_INFORMATION
            False,
            process_id.value,
        )

        if process_handle:
            try:
                executable_buffer = ctypes.create_unicode_buffer(32768)
                buffer_size = wintypes.DWORD(len(executable_buffer))

                kernel32.QueryFullProcessImageNameW.argtypes = [
                    wintypes.HANDLE,
                    wintypes.DWORD,
                    wintypes.LPWSTR,
                    ctypes.POINTER(wintypes.DWORD),
                ]
                kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

                success = kernel32.QueryFullProcessImageNameW(
                    process_handle,
                    0,
                    executable_buffer,
                    ctypes.byref(buffer_size),
                )

                if success:
                    process_path = executable_buffer.value

            finally:
                kernel32.CloseHandle(process_handle)

        process_name = (
            Path(process_path).name
            if process_path
            else None
        )

        return {
            "window_handle": int(hwnd),
            "process_id": process_id.value,
            "window_title": title_buffer.value,
            "process_path": process_path,
            "process_name": process_name,
        }

    def identify_window(self, window_info):
        if not window_info:
            return {
                "game_name": UNKNOWN_GAME,
                "matched": False,
                "window_info": None,
                "profile": None,
            }

        process_name = (
            window_info.get("process_name") or ""
        ).casefold()

        window_title = (
            window_info.get("window_title") or ""
        ).casefold()

        for profile in self.profiles:
            expected_process = profile["executable"].casefold()

            if process_name != expected_process:
                continue

            required_title_parts = profile.get(
                "title_contains",
                [],
            )

            if not all(
                str(part).casefold() in window_title
                for part in required_title_parts
            ):
                continue

            return {
                "game_name": profile["game_name"],
                "matched": True,
                "window_info": window_info,
                "profile": dict(profile),
            }

        return {
            "game_name": UNKNOWN_GAME,
            "matched": False,
            "window_info": window_info,
            "profile": None,
        }

    def detect_active_game(self):
        window_info = self.get_active_window_info()
        return self.identify_window(window_info)
