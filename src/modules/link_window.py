from PySide6.QtCore import Qt
from core.service_config import API_BASE_URL
import requests

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton
)

from modules.device import save_device_token


class LinkWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowFlags(
            self.windowFlags() |
            Qt.WindowType.WindowStaysOnTopHint
        )

        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        self.setWindowTitle("Vincular Discord")
        self.setFixedSize(300, 200)

        layout = QVBoxLayout(self)

        layout.addWidget(
            QLabel("Digite o código recebido pelo bot L no Discord:")
        )

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Código de 6 dígitos")
        self.code_input.setMaxLength(6)
        layout.addWidget(self.code_input)

        self.status = QLabel("")
        layout.addWidget(self.status)

        button = QPushButton("Vincular dispositivo")
        button.clicked.connect(self.link_device)
        layout.addWidget(button)

    def link_device(self):
        code = self.code_input.text().strip()

        if len(code) != 6 or not code.isdigit():
            self.status.setText("Digite um código válido.")
            return

        try:
            response = requests.post(
                f"{API_BASE_URL}/link",
                json={"code": code},
                timeout=15
            )

            data = response.json()

            if not response.ok:
                self.status.setText(
                    data.get("error", "Não foi possível vincular.")
                )
                return

            save_device_token(data["deviceToken"])

            self.status.setText("Dispositivo vinculado com sucesso!")

        except requests.RequestException as error:
            print(f"[LINK] Erro de conexão: {error}")
            self.status.setText("Não foi possível conectar ao servidor.")
