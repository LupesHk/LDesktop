from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QWidget,
    QDialog,
    QFrame,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QHBoxLayout,
    QSizePolicy,
)



class ReplayFullscreenDialog(QDialog):
    exit_requested = Signal()
    play_pause_requested = Signal()
    seek_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint
        )

        self.setObjectName("replayFullscreenDialog")
        self.setStyleSheet("""
            QDialog#replayFullscreenDialog {
                background-color: #050508;
                border: none;
            }
        """)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    def keyPressEvent(self, event):
        key = event.key()

        if key in (Qt.Key.Key_Escape, Qt.Key.Key_F11):
            self.exit_requested.emit()
            event.accept()
            return

        if key == Qt.Key.Key_Space:
            self.play_pause_requested.emit()
            event.accept()
            return

        if key == Qt.Key.Key_Left:
            self.seek_requested.emit(-5000)
            event.accept()
            return

        if key == Qt.Key.Key_Right:
            self.seek_requested.emit(5000)
            event.accept()
            return

        super().keyPressEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.exit_requested.emit()



class ReplayPlayerWidget(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._filepath = None
        self._duration = 0
        self.fullscreen_dialog = None

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)

        self.audio_output.setVolume(0.8)
        self.player.setAudioOutput(self.audio_output)

        self.setObjectName("replayPlayerPage")

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        self.setStyleSheet("""
            QWidget#replayPlayerPage {
                background-color: #101018;
                color: #F0EEF8;
            }

            QFrame#playerVideoFrame {
                background-color: #08080D;
                border: 1px solid #303047;
                border-radius: 13px;
            }

            QVideoWidget#replayVideo {
                background-color: #050508;
                border: none;
                border-radius: 10px;
            }

            QFrame#playerControls {
                background-color: #191923;
                border: 1px solid #303047;
                border-radius: 13px;
            }

            QLabel#playerTitle {
                color: #F5F2FF;
                font-size: 17px;
                font-weight: bold;
            }

            QLabel#playerSubtitle {
                color: #9997AD;
                font-size: 11px;
            }

            QLabel#playerStatus {
                color: #AFA0EB;
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 1px;
            }

            QLabel#playerTime {
                color: #AAA7BC;
                font-size: 11px;
            }

            QPushButton {
                background-color: #252538;
                color: #EFEDF8;
                border: 1px solid #393950;
                border-radius: 8px;
                padding: 8px 12px;
                min-height: 20px;
                font-size: 11px;
                font-weight: bold;
            }

            QPushButton:hover {
                background-color: #35334C;
                border-color: #62528E;
            }

            QPushButton#playerBackButton {
                background-color: transparent;
                border: 1px solid #393950;
                color: #C8C2D9;
                padding: 9px 12px;
            }

            QPushButton#playerBackButton:hover {
                background-color: #252538;
                color: white;
            }

            QPushButton#playerPlayButton {
                background-color: #7657E8;
                color: white;
                border: 1px solid #927AF0;
                min-width: 75px;
            }

            QPushButton#playerPlayButton:hover {
                background-color: #866CF1;
            }

            QSlider::groove:horizontal {
                height: 5px;
                background-color: #343348;
                border-radius: 2px;
            }

            QSlider::sub-page:horizontal {
                background-color: #8063ED;
                border-radius: 2px;
            }

            QSlider::handle:horizontal {
                background-color: #E9E1FF;
                border: 2px solid #8063ED;
                width: 13px;
                height: 13px;
                margin: -5px 0;
                border-radius: 7px;
            }

            QSlider::handle:horizontal:hover {
                background-color: white;
                border-color: #A18AFF;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(13)

        # Cabe?alho
        header = QHBoxLayout()
        header.setSpacing(13)

        self.back_button = QPushButton("🠸 Biblioteca")
        self.back_button.setObjectName("playerBackButton")
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)

        title_column = QVBoxLayout()
        title_column.setSpacing(3)

        self.title_label = QLabel("Player de replay")
        self.title_label.setObjectName("playerTitle")

        self.subtitle_label = QLabel(
            "Selecione um replay na biblioteca."
        )
        self.subtitle_label.setObjectName("playerSubtitle")

        title_column.addWidget(self.title_label)
        title_column.addWidget(self.subtitle_label)

        self.status_label = QLabel("PRONTO")
        self.status_label.setObjectName("playerStatus")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight |
            Qt.AlignmentFlag.AlignVCenter
        )

        header.addWidget(self.back_button)
        header.addLayout(title_column, 1)
        header.addWidget(self.status_label)

        root.addLayout(header)

        # ?rea de v?deo
        self.video_frame = QFrame()
        self.video_frame.setObjectName("playerVideoFrame")
        self.video_frame.setMinimumHeight(270)

        video_layout = QVBoxLayout(self.video_frame)
        video_layout.setContentsMargins(5, 5, 5, 5)
        video_layout.setSpacing(0)

        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("replayVideo")
        self.video_widget.setAspectRatioMode(
            Qt.AspectRatioMode.KeepAspectRatio
        )
        self.video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        video_layout.addWidget(self.video_widget)
        self.player.setVideoOutput(self.video_widget)

        root.addWidget(self.video_frame, 1)

        # Controles
        controls = QFrame()
        controls.setObjectName("playerControls")

        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(17, 12, 17, 14)
        controls_layout.setSpacing(10)

        timeline_layout = QHBoxLayout()
        timeline_layout.setSpacing(10)

        self.current_time_label = QLabel("0:00")
        self.current_time_label.setObjectName("playerTime")

        self.progress_slider = QSlider(
            Qt.Orientation.Horizontal
        )
        self.progress_slider.setRange(0, 0)
        self.progress_slider.setTracking(True)
        self.progress_slider.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.duration_label = QLabel("0:00")
        self.duration_label.setObjectName("playerTime")
        self.duration_label.setAlignment(
            Qt.AlignmentFlag.AlignRight |
            Qt.AlignmentFlag.AlignVCenter
        )

        timeline_layout.addWidget(self.current_time_label)
        timeline_layout.addWidget(self.progress_slider, 1)
        timeline_layout.addWidget(self.duration_label)

        controls_layout.addLayout(timeline_layout)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)

        self.backward_button = QPushButton("-10 s")
        self.backward_button.setToolTip(
            "Voltar 10 segundos"
        )

        self.play_button = QPushButton("Reproduzir")
        self.play_button.setObjectName("playerPlayButton")
        self.play_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.forward_button = QPushButton("+10 s")
        self.forward_button.setToolTip(
            "Avançar 10 segundos"
        )

        self.mute_button = QPushButton("Silenciar")
        self.volume_slider = QSlider(
            Qt.Orientation.Horizontal
        )
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(115)

        self.fullscreen_button = QPushButton("Tela cheia")
        self.fullscreen_button.setToolTip(
            "Alternar tela cheia"
        )

        buttons_layout.addWidget(self.backward_button)
        buttons_layout.addWidget(self.play_button)
        buttons_layout.addWidget(self.forward_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.mute_button)
        buttons_layout.addWidget(self.volume_slider)
        buttons_layout.addWidget(self.fullscreen_button)

        controls_layout.addLayout(buttons_layout)
        root.addWidget(controls)

    def _connect_signals(self):
        self.back_button.clicked.connect(
            self.back_requested.emit
        )

        self.play_button.clicked.connect(
            self.toggle_playback
        )

        self.backward_button.clicked.connect(
            lambda: self.seek_relative(-10000)
        )

        self.forward_button.clicked.connect(
            lambda: self.seek_relative(10000)
        )

        self.mute_button.clicked.connect(
            self.toggle_mute
        )

        self.volume_slider.valueChanged.connect(
            self.set_volume
        )

        self.fullscreen_button.clicked.connect(
            self.toggle_fullscreen
        )

        self.progress_slider.sliderReleased.connect(
            self.seek_to_slider_position
        )

        self.player.positionChanged.connect(
            self.update_position
        )

        self.player.durationChanged.connect(
            self.update_duration
        )

        self.player.playbackStateChanged.connect(
            self.update_playback_state
        )

        self.player.mediaStatusChanged.connect(
            self.update_media_status
        )

        self.player.errorOccurred.connect(
            self.on_error
        )


    def open_file(self, filepath):
        filepath = Path(filepath).expanduser()

        if not filepath.is_file():
            raise FileNotFoundError(str(filepath))

        if self.video_widget.isFullScreen():
            self.video_widget.setFullScreen(False)

        self.player.stop()

        self._filepath = filepath.resolve()
        self._duration = 0

        self.title_label.setText(self._filepath.stem)
        self.subtitle_label.setText(self._filepath.name)
        self.status_label.setText("CARREGANDO")

        self.progress_slider.setRange(0, 0)
        self.progress_slider.setValue(0)

        self.current_time_label.setText("0:00")
        self.duration_label.setText("0:00")

        self.player.setSource(
            QUrl.fromLocalFile(str(self._filepath))
        )

        self.player.play()

    def toggle_playback(self):
        state = self.player.playbackState()

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            return

        if self.player.mediaStatus() == (
            QMediaPlayer.MediaStatus.EndOfMedia
        ):
            self.player.setPosition(0)

        self.player.play()

    def seek_relative(self, offset):
        current = self.player.position()
        maximum = self._duration if self._duration > 0 else current + offset

        target = max(0, min(maximum, current + offset))
        self.player.setPosition(target)

    def seek_to_slider_position(self):
        self.player.setPosition(
            self.progress_slider.value()
        )

    def update_position(self, position):
        if not self.progress_slider.isSliderDown():
            self.progress_slider.setValue(position)

        self.current_time_label.setText(
            self.format_time(position)
        )

    def update_duration(self, duration):
        self._duration = max(0, duration)
        self.progress_slider.setRange(0, self._duration)
        self.duration_label.setText(
            self.format_time(self._duration)
        )

    def update_playback_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setText("Pausar")
            self.status_label.setText("REPRODUZINDO")

        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.play_button.setText("Reproduzir")
            self.status_label.setText("PAUSADO")

        else:
            self.play_button.setText("Reproduzir")

    def update_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.LoadingMedia:
            self.status_label.setText("CARREGANDO")

        elif status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.status_label.setText("PRONTO")

        elif status == QMediaPlayer.MediaStatus.BufferedMedia:
            if self.player.playbackState() != (
                QMediaPlayer.PlaybackState.PlayingState
            ):
                self.status_label.setText("PRONTO")

        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.status_label.setText("CONCLUÍDO")
            self.play_button.setText("Reproduzir novamente")

        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.status_label.setText("MÍDIA INVÁLIDA")

    def on_error(self, error, error_string):
        if error == QMediaPlayer.Error.NoError:
            return

        self.status_label.setText("ERRO NA REPRODUÇÃO")
        self.subtitle_label.setText(
            error_string or "Não foi possível reproduzir este arquivo."
        )

        print(
            f"[REPLAY PLAYER] Erro {error}: {error_string}"
        )

    def set_volume(self, value):
        self.audio_output.setVolume(value / 100.0)

        if value > 0 and self.audio_output.isMuted():
            self.audio_output.setMuted(False)
            self.mute_button.setText("Silenciar")

    def toggle_mute(self):
        muted = not self.audio_output.isMuted()
        self.audio_output.setMuted(muted)

        self.mute_button.setText(
            "Ativar som" if muted else "Silenciar"
        )


    def enter_fullscreen(self):
        if self.fullscreen_dialog is not None:
            self.fullscreen_dialog.raise_()
            self.fullscreen_dialog.activateWindow()
            return

        dialog = ReplayFullscreenDialog(self.window())

        dialog.exit_requested.connect(self.exit_fullscreen)
        dialog.play_pause_requested.connect(self.toggle_playback)
        dialog.seek_requested.connect(self.seek_relative)

        self.fullscreen_dialog = dialog

        # Move o mesmo widget de v?deo para a janela independente.
        self.video_widget.setParent(dialog)
        dialog.layout().addWidget(self.video_widget)

        self.video_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.video_widget.show()

        dialog.showFullScreen()
        dialog.raise_()
        dialog.activateWindow()
        dialog.setFocus()

        self.update_fullscreen_state(True)

    def exit_fullscreen(self):
        dialog = self.fullscreen_dialog

        if dialog is None:
            return

        self.fullscreen_dialog = None

        dialog.hide()
        dialog.layout().removeWidget(self.video_widget)

        self.video_widget.setParent(self.video_frame)
        self.video_frame.layout().addWidget(self.video_widget)
        self.video_widget.show()
        self.video_frame.show()

        dialog.deleteLater()

        self.update_fullscreen_state(False)



    def toggle_fullscreen(self):
        if self.fullscreen_dialog is not None:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()



    def update_fullscreen_state(self, fullscreen):
        self.fullscreen_button.setText(
            "Sair da tela cheia" if fullscreen else "Tela cheia"
        )
        self.fullscreen_button.setToolTip(
            "Pressione ESC ou F11 para sair"
            if fullscreen else "Alternar tela cheia"
        )



    def stop(self):
        if self.fullscreen_dialog is not None:
            self.exit_fullscreen()

        self.player.stop()
        self.player.setSource(QUrl())

        self._filepath = None
        self._duration = 0

        self.progress_slider.setRange(0, 0)
        self.progress_slider.setValue(0)

        self.current_time_label.setText("0:00")
        self.duration_label.setText("0:00")
        self.play_button.setText("Reproduzir")
        self.status_label.setText("PRONTO")


    @staticmethod
    def format_time(milliseconds):
        total_seconds = max(0, int(milliseconds // 1000))

        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"

        return f"{minutes}:{seconds:02d}"
