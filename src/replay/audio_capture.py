import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import soundcard as sc
import sounddevice as sd
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

        # Captura do áudio do sistema: mantém SoundCard.
        try:
            speaker = sc.default_speaker()

            system_device = sc.get_microphone(
                id=str(speaker.name),
                include_loopback=True,
            )

            system_thread = threading.Thread(
                target=self._capture_loop,
                args=(system_device, self.system_chunks, 2, "Sistema"),
                daemon=True,
                name="AudioCapture-Sistema",
            )

            self.threads.append(system_thread)
            system_thread.start()

        except Exception as error:
            self.errors.append(f"Sistema: {error}")
            print(f"[AUDIO] Falha ao iniciar áudio do sistema: {error}")

        # Captura do microfone: utiliza SoundDevice.
        settings = load_audio_settings()
        selected_id = settings.get("microphone_id")

        try:
            microphone = resolve_microphone(selected_id)

            print(
                f"[AUDIO] Microfone selecionado: "
                f"{microphone['name']}"
            )
            print(
                f"[AUDIO] API: {microphone['hostapi']} | "
                f"ID: {microphone['id']}"
            )

            microphone_thread = threading.Thread(
                target=self._capture_microphone_loop,
                args=(microphone,),
                daemon=True,
                name="AudioCapture-Microfone",
            )

            self.threads.append(microphone_thread)
            microphone_thread.start()

        except Exception as error:
            self.errors.append(f"Microfone indisponível: {error}")
            print(f"[AUDIO] Falha ao selecionar microfone: {error}")

        if not self.threads:
            raise RuntimeError(
                "Não foi possível iniciar nenhuma captura de áudio."
            )

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

                    timestamp = time.monotonic() - (len(audio) / self.SAMPLE_RATE)

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

    def _capture_microphone_loop(self, microphone):
        frames = int(self.SAMPLE_RATE * self.CHUNK_SECONDS)
        blocksize = int(self.SAMPLE_RATE * self.BLOCKSIZE_SECONDS)

        extra_settings = None

        if microphone["hostapi"] == "Windows WASAPI":
            extra_settings = sd.WasapiSettings(auto_convert=True)

        try:
            with sd.InputStream(
                device=microphone["index"],
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=blocksize,
                extra_settings=extra_settings,
            ) as stream:

                print(
                    "[AUDIO] Microfone aberto e capturando: "
                    f"{microphone['name']}"
                )

                while not self.stop_event.is_set():
                    audio, overflowed = stream.read(frames)
                    timestamp = time.monotonic() - (len(audio) / self.SAMPLE_RATE)

                    if len(audio) == 0:
                        continue

                    if overflowed:
                        print(
                            "[AUDIO] Aviso: overflow na captura "
                            "do microfone."
                        )

                    audio = np.asarray(
                        audio,
                        dtype=np.float32,
                    )

                    with self.lock:
                        self.microphone_chunks.append(
                            (timestamp, audio)
                        )

                        cutoff = timestamp - self.BUFFER_SECONDS

                        while (
                            self.microphone_chunks
                            and self.microphone_chunks[0][0] < cutoff
                        ):
                            self.microphone_chunks.popleft()

        except Exception as error:
            self.errors.append(f"Microfone: {error}")
            print(f"[AUDIO] Erro no microfone: {error}")

    def get_mixed_audio(self, duration=30, end_time=None):
        with self.lock:
            system_chunks = list(self.system_chunks)
            microphone_chunks = list(self.microphone_chunks)

        if not system_chunks:
            raise RuntimeError("Nenhum áudio do sistema foi capturado.")

        if end_time is None:
            system_end = (
                system_chunks[-1][0]
                + len(system_chunks[-1][1]) / self.SAMPLE_RATE
            )
            end_time = system_end

            if microphone_chunks:
                microphone_end = (
                    microphone_chunks[-1][0]
                    + len(microphone_chunks[-1][1]) / self.SAMPLE_RATE
                )
                end_time = min(end_time, microphone_end)

        start_time = end_time - duration
        total_frames = int(duration * self.SAMPLE_RATE)

        system_audio = np.zeros((total_frames, 2), dtype=np.float32)
        microphone_audio = np.zeros((total_frames, 2), dtype=np.float32)

        def insert_chunks(chunks, destination, channels):
            if not chunks:
                return

            first_timestamp = chunks[0][0]
            cursor = int(round(
                (first_timestamp - start_time) * self.SAMPLE_RATE
            ))

            for _, audio in chunks:
                audio = np.asarray(audio, dtype=np.float32)

                source_start = max(0, -cursor)
                target_start = max(0, cursor)

                available = min(
                    len(audio) - source_start,
                    total_frames - target_start
                )

                if available > 0:
                    chunk = audio[
                        source_start:source_start + available
                    ]

                    if channels == 1:
                        chunk = np.repeat(chunk, 2, axis=1)

                    destination[
                        target_start:target_start + available
                    ] = chunk

                cursor += len(audio)

                if cursor >= total_frames:
                    break

        insert_chunks(system_chunks, system_audio, 2)
        insert_chunks(microphone_chunks, microphone_audio, 1)

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
