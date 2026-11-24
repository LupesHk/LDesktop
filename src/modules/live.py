
import threading
import time

import requests

from PySide6.QtCore import QThread, Signal

from core.service_config import API_BASE_URL
from modules.device import get_device_token


class LiveService(QThread):
    connection_changed = Signal(bool, str)
    friends_updated = Signal(object)

    HEARTBEAT_INTERVAL = 8
    FRIENDS_INTERVAL = 8

    def __init__(self, parent=None):
        super().__init__(parent)

        self.base_url = API_BASE_URL.rstrip("/")
        self._stop_event = threading.Event()
        self._last_connection_state = None

    def stop(self):
        self._stop_event.set()

    def _set_connection(self, online, message):
        if self._last_connection_state == online:
            return

        self._last_connection_state = online
        self.connection_changed.emit(online, message)

    def _disconnect(self, session, token):
        try:
            response = session.post(
                f"{self.base_url}/live/disconnect",
                headers={"x-device-token": token},
                timeout=3,
            )

            response.raise_for_status()
            print("[LIVE] Presença encerrada no servidor.")

        except Exception as error:
            print(f"[LIVE] Não foi possível encerrar a presença: {error}")

    def _refresh_friends(self, session, token):
        try:
            response = session.get(
                f"{self.base_url}/live/friends",
                headers={"x-device-token": token},
                timeout=5,
            )

            response.raise_for_status()
            data = response.json()

            if data.get("success"):
                friends = data.get("friends", [])

                if isinstance(friends, list):
                    self.friends_updated.emit(friends)

        except Exception as error:
            print(f"[LIVE] Erro ao consultar amigos: {error}")

    def run(self):
        session = requests.Session()

        current_token = None
        next_friends_update = 0

        print("[LIVE] Serviço iniciado.")

        try:
            while not self._stop_event.is_set():

                try:
                    token = get_device_token()

                    # Detecta vinculação ou troca de dispositivo.
                    if token != current_token:
                        if current_token:
                            self._disconnect(session, current_token)

                        current_token = token
                        next_friends_update = 0

                    if not current_token:
                        self._set_connection(
                            False,
                            "Dispositivo não vinculado."
                        )

                    else:
                        try:
                            response = session.post(
                                f"{self.base_url}/live/heartbeat",
                                headers={
                                    "x-device-token": current_token
                                },
                                timeout=5,
                            )

                            response.raise_for_status()
                            data = response.json()

                            if not data.get("success"):
                                raise RuntimeError(
                                    data.get(
                                        "error",
                                        "Heartbeat recusado."
                                    )
                                )

                            self._set_connection(
                                True,
                                "Presença ativa."
                            )

                            now = time.monotonic()

                            if now >= next_friends_update:
                                self._refresh_friends(
                                    session,
                                    current_token,
                                )

                                next_friends_update = (
                                    time.monotonic()
                                    + self.FRIENDS_INTERVAL
                                )

                        except Exception as error:
                            self._set_connection(
                                False,
                                f"API indisponível: {error}"
                            )

                            print(f"[LIVE] Erro de conexão: {error}")

                except Exception as error:
                    self._set_connection(
                        False,
                        "Erro ao verificar dispositivo."
                    )

                    print(f"[LIVE] Erro interno: {error}")

                self._stop_event.wait(self.HEARTBEAT_INTERVAL)

        finally:
            if current_token:
                self._disconnect(session, current_token)

            session.close()

            self._set_connection(
                False,
                "Presença encerrada."
            )

            print("[LIVE] Serviço finalizado.")
