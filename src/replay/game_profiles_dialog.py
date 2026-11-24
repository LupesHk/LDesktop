from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QListWidget,
    QLineEdit,
    QPushButton,
    QFileDialog,
)

from replay.game_detector import GameDetector, DEFAULT_PROFILES


class GameProfilesDialog(QDialog):

    def __init__(self, detector, parent=None):
        super().__init__(parent)

        self.detector = detector
        self.selected_index = None

        self.setWindowTitle("Gerenciar jogos")
        self.resize(760, 520)
        self.setMinimumSize(650, 440)

        self.setup_ui()
        self.refresh_profiles()

    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        heading = QLabel("GERENCIAMENTO DE JOGOS")
        heading.setObjectName("cardTitle")

        description = QLabel(
            "Configure os execut\u00e1veis que o L Desktop "
            "deve reconhecer durante os replays."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)

        root.addWidget(heading)
        root.addWidget(description)

        content = QHBoxLayout()
        content.setSpacing(18)

        # Lista de jogos.
        left = QVBoxLayout()

        list_title = QLabel("PERFIS CADASTRADOS")
        list_title.setObjectName("cardTitle")

        self.profile_list = QListWidget()
        self.profile_list.setMinimumWidth(260)
        self.profile_list.currentRowChanged.connect(
            self.load_selected_profile
        )

        left.addWidget(list_title)
        left.addWidget(self.profile_list, 1)

        # Formulario.
        right = QVBoxLayout()

        form_title = QLabel("DADOS DO JOGO")
        form_title.setObjectName("cardTitle")

        form = QFormLayout()
        form.setSpacing(13)

        self.game_name_input = QLineEdit()
        self.game_name_input.setPlaceholderText("Ex.: Minecraft")

        self.executable_input = QLineEdit()
        self.executable_input.setPlaceholderText("Ex.: javaw.exe")

        browse_button = QPushButton("Procurar...")
        browse_button.clicked.connect(self.browse_executable)

        executable_row = QHBoxLayout()
        executable_row.addWidget(self.executable_input, 1)
        executable_row.addWidget(browse_button)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText(
            "Ex.: minecraft, singleplayer"
        )

        form.addRow("Nome do jogo:", self.game_name_input)
        form.addRow("Execut\u00e1vel:", executable_row)
        form.addRow("T\u00edtulo cont\u00e9m:", self.title_input)

        title_help = QLabel(
            "Opcional. Separe por v\u00edrgulas. "
            "Todas as palavras informadas devem aparecer "
            "no t\u00edtulo da janela."
        )
        title_help.setObjectName("muted")
        title_help.setWordWrap(True)

        right.addWidget(form_title)
        right.addLayout(form)
        right.addWidget(title_help)

        self.status_label = QLabel("Selecione um perfil ou crie um novo.")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)

        right.addWidget(self.status_label)
        right.addStretch()

        content.addLayout(left, 1)
        content.addLayout(right, 2)

        root.addLayout(content, 1)

        # Acoes.
        actions = QHBoxLayout()

        new_button = QPushButton("Novo perfil")
        new_button.clicked.connect(self.new_profile)

        self.remove_button = QPushButton("Remover")
        self.remove_button.setObjectName("dangerButton")
        self.remove_button.clicked.connect(self.remove_profile)

        reset_button = QPushButton("Restaurar padr\u00f5es")
        reset_button.clicked.connect(self.restore_defaults)

        close_button = QPushButton("Fechar")
        close_button.clicked.connect(self.accept)

        save_button = QPushButton("Salvar perfil")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self.save_profile)

        actions.addWidget(new_button)
        actions.addWidget(self.remove_button)
        actions.addWidget(reset_button)
        actions.addStretch()
        actions.addWidget(close_button)
        actions.addWidget(save_button)

        root.addLayout(actions)

    def refresh_profiles(self, selected_index=None):
        self.profile_list.blockSignals(True)
        self.profile_list.clear()

        for profile in self.detector.list_profiles():
            title = ", ".join(
                profile.get("title_contains", [])
            )

            label = (
                f"{profile['game_name']} "
                f"\u2014 {profile['executable']}"
            )

            if title:
                label += f"\nJanela: {title}"

            self.profile_list.addItem(label)

        if selected_index is not None:
            if 0 <= selected_index < self.profile_list.count():
                self.profile_list.setCurrentRow(selected_index)
            else:
                self.profile_list.setCurrentRow(-1)
        else:
            self.profile_list.setCurrentRow(-1)

        self.profile_list.blockSignals(False)

        self.selected_index = selected_index
        self.remove_button.setEnabled(
            selected_index is not None
            and 0 <= selected_index < len(self.detector.profiles)
        )

    def load_selected_profile(self, index):
        if index < 0 or index >= len(self.detector.profiles):
            return

        profile = self.detector.profiles[index]

        self.selected_index = index
        self.game_name_input.setText(profile["game_name"])
        self.executable_input.setText(profile["executable"])
        self.title_input.setText(
            ", ".join(profile.get("title_contains", []))
        )

        self.remove_button.setEnabled(True)
        self.status_label.setText("Perfil selecionado para edi\u00e7\u00e3o.")

    def new_profile(self):
        self.profile_list.blockSignals(True)
        self.profile_list.clearSelection()
        self.profile_list.setCurrentRow(-1)
        self.profile_list.blockSignals(False)

        self.selected_index = None

        self.game_name_input.clear()
        self.executable_input.clear()
        self.title_input.clear()

        self.remove_button.setEnabled(False)
        self.status_label.setText("Preencha os dados do novo jogo.")

        self.game_name_input.setFocus()

    def browse_executable(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar execut\u00e1vel do jogo",
            "",
            "Execut\u00e1veis (*.exe)",
        )

        if filepath:
            self.executable_input.setText(filepath)

    def save_profile(self):
        game_name = self.game_name_input.text().strip()
        executable = self.executable_input.text().strip()

        title_contains = [
            item.strip()
            for item in self.title_input.text().split(",")
            if item.strip()
        ]

        if not game_name:
            self.status_label.setText("Informe o nome do jogo.")
            self.game_name_input.setFocus()
            return

        if not executable:
            self.status_label.setText("Selecione o execut\u00e1vel do jogo.")
            self.executable_input.setFocus()
            return

        executable = Path(executable).name

        if not executable.lower().endswith(".exe"):
            self.status_label.setText(
                "O execut\u00e1vel precisa terminar em .exe."
            )
            return

        profile = {
            "game_name": game_name,
            "executable": executable,
            "title_contains": title_contains,
        }

        try:
            if self.selected_index is None:
                self.detector.add_profile(
                    game_name,
                    executable,
                    title_contains,
                )

                selected = next(
                    (
                        index
                        for index, item in enumerate(
                            self.detector.profiles
                        )
                        if item == profile
                    ),
                    len(self.detector.profiles) - 1,
                )

            else:
                self.detector.profiles[self.selected_index] = profile
                self.detector._validate_profiles()
                self.detector.save_profiles()
                selected = self.selected_index

            self.refresh_profiles(selected)
            self.status_label.setText("Perfil salvo com sucesso.")

        except (OSError, ValueError, IndexError) as error:
            self.status_label.setText(f"Erro ao salvar perfil: {error}")

    def remove_profile(self):
        index = self.selected_index

        if index is None or not 0 <= index < len(self.detector.profiles):
            return

        profile = self.detector.profiles[index]

        self.detector.profiles.pop(index)
        self.detector.save_profiles()

        self.refresh_profiles()
        self.new_profile()

        self.status_label.setText(
            f"Perfil removido: {profile['game_name']}."
        )

    def restore_defaults(self):
        self.detector.profiles = [
            dict(profile)
            for profile in DEFAULT_PROFILES
        ]

        self.detector.save_profiles()
        self.refresh_profiles()

        self.status_label.setText(
            "Perfis padr\u00e3o restaurados."
        )
