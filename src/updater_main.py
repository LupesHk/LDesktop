
import argparse
import ctypes
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid

from pathlib import Path
from ctypes import wintypes


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.OpenProcess.argtypes = [
    wintypes.DWORD,
    wintypes.BOOL,
    wintypes.DWORD
]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.WaitForSingleObject.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD
]
kernel32.WaitForSingleObject.restype = wintypes.DWORD

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
ERROR_INVALID_PARAMETER = 87

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def wait_for_process(pid, timeout_ms=120000):
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)

    if not handle:
        error = ctypes.get_last_error()

        if error == ERROR_INVALID_PARAMETER:
            return

        raise ctypes.WinError(error)

    try:
        result = kernel32.WaitForSingleObject(handle, timeout_ms)

        if result == WAIT_TIMEOUT:
            raise TimeoutError(
                "O L Desktop não encerrou dentro do prazo."
            )

        if result != WAIT_OBJECT_0:
            raise ctypes.WinError(ctypes.get_last_error())

    finally:
        kernel32.CloseHandle(handle)


def launch_app_and_confirm(app_exe, app_dir, timeout_seconds=45):
    event_name = (
        f"Local\\LDesktop_UpdateConfirm_{uuid.uuid4().hex}"
    )

    kernel32.CreateEventW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    event_handle = kernel32.CreateEventW(
        None,
        True,
        False,
        event_name,
    )

    if not event_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    app_process = None

    try:
        app_process = subprocess.Popen(
            [
                str(app_exe),
                "--update-confirmation",
                event_name,
            ],
            cwd=str(app_dir),
            creationflags=CREATE_NO_WINDOW,
        )

        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            result = kernel32.WaitForSingleObject(
                event_handle,
                500,
            )

            if result == WAIT_OBJECT_0:
                logging.info(
                    "Nova versão confirmou a inicialização."
                )
                return app_process

            if result != WAIT_TIMEOUT:
                raise ctypes.WinError(ctypes.get_last_error())

            if app_process.poll() is not None:
                raise RuntimeError(
                    "O aplicativo encerrou antes de confirmar "
                    "a inicialização."
                )

        raise TimeoutError(
            "A nova versão não confirmou a inicialização "
            f"em {timeout_seconds} segundos."
        )

    except Exception:
        if app_process is not None and app_process.poll() is None:
            app_process.terminate()

            try:
                app_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                app_process.kill()
                app_process.wait()

        raise

    finally:
        kernel32.CloseHandle(event_handle)

def show_error(message):
    ctypes.windll.user32.MessageBoxW(
        None,
        str(message),
        "Atualizador do L Desktop",
        0x10
    )


def restore_backup(app_dir, backup_dir):
    logging.warning("Iniciando restauração do backup.")

    if app_dir.exists():
        shutil.rmtree(app_dir)

    shutil.copytree(backup_dir, app_dir)

    logging.info("Backup restaurado com sucesso.")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--installer", required=True)
    parser.add_argument("--app-exe", required=True)

    args = parser.parse_args()

    installer = Path(args.installer).resolve()
    app_exe = Path(args.app_exe).resolve()
    app_dir = app_exe.parent

    local_appdata = Path(
        os.environ.get("LOCALAPPDATA", Path.home())
    )

    update_dir = local_appdata / "LDesktop" / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)

    log_path = update_dir / "updater.log"
    backup_dir = update_dir / "rollback"

    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8"
    )

    backup_created = False
    installation_started = False
    parent_exited = False

    try:
        if not installer.is_file():
            raise FileNotFoundError(
                f"Instalador não encontrado: {installer}"
            )

        if installer.suffix.lower() != ".exe":
            raise ValueError("O pacote de atualização não é um EXE.")

        logging.info("Aguardando encerramento do L Desktop.")
        wait_for_process(args.parent_pid)
        parent_exited = True

        # Backup da instalação atual.
        if app_dir.exists():
            logging.info("Criando backup da instalação atual.")

            if backup_dir.exists():
                shutil.rmtree(backup_dir)

            shutil.copytree(app_dir, backup_dir)
            backup_created = True

            logging.info("Backup criado em: %s", backup_dir)

        # Executa o instalador.
        logging.info("Executando instalador: %s", installer)

        command = [
            str(installer),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            f"/LOG={log_path}"
        ]

        installation_started = True

        result = subprocess.run(
            command,
            cwd=str(installer.parent),
            timeout=600,
            creationflags=CREATE_NO_WINDOW
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"O instalador retornou código {result.returncode}."
            )

        if not app_exe.exists():
            raise FileNotFoundError(
                "O executável do L Desktop não foi encontrado após a instalação."
            )

        launch_app_and_confirm(app_exe, app_dir)

        logging.info("L Desktop reaberto.")



    except Exception as error:
        logging.exception("Falha durante a atualização.")

        rollback_succeeded = not installation_started
        rollback_error = None

        if installation_started and backup_created:
            try:
                restore_backup(app_dir, backup_dir)
                rollback_succeeded = True
                logging.info("Rollback concluído com sucesso.")
            except Exception as restore_error:
                rollback_error = restore_error
                rollback_succeeded = False
                logging.exception("Falha ao restaurar o backup.")

        elif installation_started and not backup_created:
            rollback_succeeded = False
            logging.critical(
                "Instalação iniciada sem backup disponível."
            )

        if parent_exited and rollback_succeeded and app_exe.exists():
            try:
                subprocess.Popen(
                    [str(app_exe)],
                    cwd=str(app_dir),
                    creationflags=CREATE_NO_WINDOW,
                )
            except Exception:
                logging.exception(
                    "Não foi possível reiniciar o aplicativo."
                )

        message = f"A atualização falhou: {error}"

        if rollback_error:
            message += (
                "\n\nATENÇÃO: também houve uma falha ao restaurar "
                f"a versão anterior: {rollback_error}"
                f"\nConsulte o log: {log_path}"
            )
        elif installation_started and backup_created:
            message += "\n\nA versão anterior foi restaurada."
        elif installation_started and not backup_created:
            message += (
                "\n\nATENÇÃO: não havia backup disponível. "
                "O aplicativo não foi reiniciado automaticamente."
            )

        show_error(message)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
