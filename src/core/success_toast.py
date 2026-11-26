from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class SuccessToast(QFrame):
    dismissed = Signal(object)

    def __init__(self, title, message):
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )

        self._dismissed = False
        self.setObjectName("successDesktopToast")
        self.setFixedSize(340, 112)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet("""
            QFrame#successDesktopToast {
                background-color: #211b35;
                border: 1px solid #7654b8;
                border-radius: 12px;
            }
            QLabel {
                color: #ffffff;
                background: transparent;
                border: none;
            }
            QPushButton {
                color: white;
                background-color: #7046b8;
                border: none;
                border-radius: 7px;
                padding: 4px 9px;
                font-weight: 600;
            }
            QPushButton#toastClose {
                background: transparent;
                color: #bdb5cc;
                font-size: 19px;
                padding: 1px 7px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 11, 15, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        status = QLabel("✓ CONCLUÍDO")
        status.setStyleSheet("color: #a8e6bd; font-weight: 700;")

        close_button = QPushButton("×")
        close_button.setObjectName("toastClose")
        close_button.setFixedSize(28, 26)
        close_button.clicked.connect(self.dismiss)

        top.addWidget(status)
        top.addStretch()
        top.addWidget(close_button)
        layout.addLayout(top)

        heading = QLabel(str(title))
        heading.setStyleSheet("font-size: 14px; font-weight: 700;")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        description = QLabel(str(message))
        description.setStyleSheet("color: #c5bfd2; font-size: 11px;")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.timer.start(5000)

    def dismiss(self):
        if self._dismissed:
            return

        self._dismissed = True
        self.timer.stop()
        self.dismissed.emit(self)
