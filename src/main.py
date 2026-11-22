
import argparse
import ctypes
import os
import sys
from ctypes import wintypes

MUTEX_NAME = "Local\\LDesktop_SingleInstance"
ERROR_ALREADY_EXISTS = 183

_mutex_handle = None


def acquire_single_instance():
    global _mutex_handle

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.CreateMutexW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)

    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)

        ctypes.windll.user32.MessageBoxW(
            None,
            "O L Desktop já está em execução.",
            "L Desktop",
            0x40,
        )
        return False

    _mutex_handle = handle
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--update-confirmation", default=None)

    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0], *remaining]

    if acquire_single_instance():
        os.environ["LDESKTOP_UPDATE_CONFIRMATION"] = (
            args.update_confirmation or ""
        )

        from core.app import main
        main()
