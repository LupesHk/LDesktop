import queue
import threading

import numpy as np
import sounddevice as sd


class LiveAudioPlayback:
    SAMPLE_RATE = 48000
    CHANNELS = 2
    BLOCK_SIZE = 480

    def __init__(self):
        self._queue = queue.Queue(maxsize=25)
        self._lock = threading.Lock()
        self._volume = 1.0
        self._stopped = threading.Event()
        self._thread = None
        self._stream = None
        self.error = None

    def start(self):
        self._stream = sd.RawOutputStream(
            samplerate=self.SAMPLE_RATE,
            channels=self.CHANNELS,
            dtype="int16",
            blocksize=self.BLOCK_SIZE,
            latency="low",
        )
        self._stream.start()

        self._thread = threading.Thread(
            target=self._play_loop,
            name="LiveAudioPlayback",
            daemon=True,
        )
        self._thread.start()

    def set_volume(self, value):
        with self._lock:
            self._volume = max(0.0, min(1.0, float(value)))

    def enqueue(self, data):
        if self._stopped.is_set():
            return

        raw = bytes(data)

        try:
            self._queue.put_nowait(raw)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self._queue.put_nowait(raw)
            except queue.Full:
                pass

    def _play_loop(self):
        try:
            while not self._stopped.is_set():
                try:
                    data = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if data is None:
                    break

                with self._lock:
                    volume = self._volume

                samples = np.frombuffer(data, dtype=np.int16)

                if volume <= 0:
                    output = bytes(len(data))
                elif volume >= 0.999:
                    output = data
                else:
                    adjusted = np.clip(
                        samples.astype(np.float32) * volume,
                        -32768,
                        32767,
                    ).astype(np.int16)
                    output = adjusted.tobytes()

                self._stream.write(output)

        except Exception as error:
            self.error = error
            self._stopped.set()

    def stop(self):
        was_stopped = self._stopped.is_set()
        self._stopped.set()

        if not was_stopped:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(None)
                except queue.Empty:
                    pass

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

        if self._stream:
            stream = self._stream
            self._stream = None

            try:
                stream.stop()
            except Exception:
                pass
            finally:
                stream.close()

        print("[LIVE AUDIO] Reprodução local encerrada.")
