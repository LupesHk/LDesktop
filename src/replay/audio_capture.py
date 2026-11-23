
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import soundcard as sc
import soundfile as sf

from core.audio_config import (
    load_audio_settings,
    resolve_microphone,
)


class AudioCapture:

    SAMPLE_RATE = 48000
    CHUNK_SECONDS = 0.05
    BLOCKSIZE_SECONDS = 0.20
    BUFFER_SECONDS = 32

    SYSTEM_VOLUME = 0.60
    MICROPHONE_VOLUME = 0.85

    def __init__(self):
        self.system_chunks = deque()
        self.microphone_chunks = deque()

        self.lock = threading.Lock()
        self.stop_event = threading.Event()

        self.threads = []
        self.errors = []

    def start(self):
        if self.threads:
            return

        self.stop_event.clear()
        self.errors.clear()

        with self.lock:
            self.system_chunks.clear()
            self.microphone_chunks.clear()

        speaker = sc.default_speaker()

        system_device = sc.get_microphone(
            id=str(speaker.name),
            include_loopback=True,
        )

        devices = [
            (system_device, self.system_chunks, 2, "Sistema")
        ]

        settings = load_audio_settings()
        selected_id = settings.get("microphone_id")

        try:
            microphone_device = resolve_microphone(selected_id)

            devices.append(
                (
                    microphone_device,
                    self.microphone_chunks,
                    1,
                    "Microfone",
                )
            )

            print(
                f"[AUDIO] Microfone selecionado: "
                f"{microphone_device.name}"
            )

            print(
                f"[AUDIO] ID do microfone: "
                f"{microphone_device.id}"
            )

        except Exception as error:
            self.errors.append(f"Microfone indisponível: {error}")

            print(f"[AUDIO] Falha ao selecionar microfone: {error}")

            if selected_id is None:
                print(
                    "[AUDIO] O microfone padrão do Windows "
                    "não está disponível."
                )

            else:
                print(
                    "[AUDIO] O dispositivo salvo não foi encontrado. "
                    "Escolha outro na configuração de áudio."
                )

        for device, buffer, channels, name in devices:
            thread = threading.Thread(
                target=self._capture_loop,
                args=(device, buffer, channels, name),
                daemon=True,
                name=f"AudioCapture-{name}",
            )

            self.threads.append(thread)
            thread.start()

        print("[AUDIO] Captura de áudio iniciada.")

    def _capture_loop(self, device, buffer, channels, name):
        frames = int(
            self.SAMPLE_RATE * self.CHUNK_SECONDS
        )

        blocksize = int(
            self.SAMPLE_RATE * self.BLOCKSIZE_SECONDS
        )

        try:
            with device.recorder(
                samplerate=self.SAMPLE_RATE,
                channels=channels,
                blocksize=blocksize,
            ) as recorder:

                print(
                    f"[AUDIO] Dispositivo aberto e capturando: {name}"
                )

                while not self.stop_event.is_set():
                    audio = recorder.record(numframes=frames)

                    if len(audio) == 0:
                        continue

                    timestamp = time.monotonic()

                    audio = np.asarray(
                        audio,
                        dtype=np.float32,
                    )

                    with self.lock:
                        buffer.append((timestamp, audio))

                        cutoff = timestamp - self.BUFFER_SECONDS

                        while buffer and buffer[0][0] < cutoff:
                            buffer.popleft()

        except Exception as error:
            self.errors.append(f"{name}: {error}")
            print(f"[AUDIO] Erro em {name}: {error}")

    def get_mixed_audio(self, duration=30, end_time=None):
        with self.lock:
            system_chunks = list(self.system_chunks)
            microphone_chunks = list(self.microphone_chunks)

        if not system_chunks:
            raise RuntimeError(
                "Ainda não existem dados suficientes de áudio do sistema."
            )

        if end_time is None:
            end_time = system_chunks[-1][0]

            if microphone_chunks:
                end_time = min(
                    end_time,
                    microphone_chunks[-1][0],
                )

        start_time = end_time - duration
        total_frames = int(duration * self.SAMPLE_RATE)

        system_audio = np.zeros(
            (total_frames, 2),
            dtype=np.float32,
        )

        microphone_audio = np.zeros(
            (total_frames, 2),
            dtype=np.float32,
        )

        def insert_chunks(chunks, destination, channels):
            for timestamp, audio in chunks:
                chunk_duration = len(audio) / self.SAMPLE_RATE
                chunk_start = timestamp - chunk_duration

                offset = int(
                    round(
                        (chunk_start - start_time)
                        * self.SAMPLE_RATE
                    )
                )

                source_start = max(0, -offset)
                target_start = max(0, offset)

                available = min(
                    len(audio) - source_start,
                    total_frames - target_start,
                )

                if available <= 0:
                    continue

                chunk = audio[
                    source_start:source_start + available
                ]

                if channels == 1:
                    chunk = np.repeat(chunk, 2, axis=1)

                destination[
                    target_start:target_start + available
                ] = chunk

        insert_chunks(
            system_chunks,
            system_audio,
            2,
        )

        if microphone_chunks:
            insert_chunks(
                microphone_chunks,
                microphone_audio,
                1,
            )

        mixed = (
            system_audio * self.SYSTEM_VOLUME
            + microphone_audio * self.MICROPHONE_VOLUME
        )

        peak = np.max(np.abs(mixed))

        if peak > 0.98:
            mixed *= 0.98 / peak

        return mixed

    def save_wav(self, filepath, duration=30, end_time=None):
        audio = self.get_mixed_audio(
            duration=duration,
            end_time=end_time,
        )

        filepath = Path(filepath)

        sf.write(
            str(filepath),
            audio,
            self.SAMPLE_RATE,
            subtype="PCM_16",
        )

        print(f"[AUDIO] Áudio salvo: {filepath}")

        return filepath

    def stop(self):
        self.stop_event.set()

        for thread in self.threads:
            thread.join(timeout=3)

        self.threads.clear()

        print("[AUDIO] Captura de áudio encerrada.")
