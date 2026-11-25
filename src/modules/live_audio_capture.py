import asyncio
import os
import subprocess
import threading
from pathlib import Path

from core.paths import RESOURCE_DIR


class LiveAudioCapture:
    SAMPLE_RATE = 48000
    CHANNELS = 2
    SAMPLES_PER_CHANNEL = 480
    FRAME_BYTES = SAMPLES_PER_CHANNEL * CHANNELS * 2

    def __init__(self):
        resource_dir = Path(RESOURCE_DIR)

        candidates = [
            resource_dir / "LiveAudioCapture" / "LiveAudioCapture.exe",
            resource_dir / "bin" / "LiveAudioCapture" / "LiveAudioCapture.exe",
            Path(__file__).resolve().parents[2]
            / "bin" / "LiveAudioCapture" / "LiveAudioCapture.exe",
        ]

        self.executable = next(
            (path for path in candidates if path.is_file()),
            None,
        )

        self.process = None
        self._loop = None
        self._frames = None
        self._ready = threading.Event()
        self._startup_error = None
        self._stderr_thread = None
        self._stdout_thread = None

    async def start(self):
        if self.executable is None:
            raise FileNotFoundError(
                "O componente LiveAudioCapture.exe não foi encontrado."
            )

        self._loop = asyncio.get_running_loop()
        self._frames = asyncio.Queue(maxsize=30)

        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self.process = subprocess.Popen(
            [str(self.executable), "capture"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=creation_flags,
        )

        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="LiveAudioStderr",
            daemon=True,
        )
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="LiveAudioPcm",
            daemon=True,
        )

        self._stderr_thread.start()
        self._stdout_thread.start()

        # Evita asyncio.to_thread: no ambiente Python 3.15 + Qt,
        # o executor pode falhar ao resolver imports tardios.
        deadline = self._loop.time() + 15

        while not self._ready.is_set():
            if self.process.poll() is not None:
                break

            if self._loop.time() >= deadline:
                await self.stop()
                raise TimeoutError(
                    "O capturador de áudio não inicializou em 15 segundos."
                )

            await asyncio.sleep(0.025)

        if self._startup_error:
            error = self._startup_error
            await self.stop()
            raise RuntimeError(error)

        if self.process.poll() is not None:
            code = self.process.returncode
            await self.stop()
            raise RuntimeError(
                f"O capturador encerrou durante a inicialização ({code})."
            )

        print(
            "[LIVE AUDIO] Captura iniciada. "
            "Discord excluído da árvore de processos."
        )

    def _read_stderr(self):
        try:
            for raw in iter(self.process.stderr.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()

                if not line:
                    continue

                print(f"[LIVE AUDIO AUX] {line}")

                if line.startswith("READY|"):
                    self._ready.set()
                elif line.startswith("ERROR|"):
                    self._startup_error = line
                    self._ready.set()
        finally:
            self._ready.set()

    def _read_stdout(self):
        pending = bytearray()

        try:
            descriptor = self.process.stdout.fileno()

            while True:
                chunk = os.read(descriptor, 8192)

                if not chunk:
                    break

                pending.extend(chunk)

                while len(pending) >= self.FRAME_BYTES:
                    frame = bytes(pending[:self.FRAME_BYTES])
                    del pending[:self.FRAME_BYTES]

                    try:
                        self._loop.call_soon_threadsafe(
                            self._enqueue_frame,
                            frame,
                        )
                    except RuntimeError:
                        return
        except (OSError, ValueError):
            pass

    def _enqueue_frame(self, frame):
        if self._frames is None:
            return

        if self._frames.full():
            try:
                self._frames.get_nowait()
            except asyncio.QueueEmpty:
                pass

        try:
            self._frames.put_nowait(frame)
        except asyncio.QueueFull:
            pass

    async def get_frame(self):
        while True:
            try:
                return await asyncio.wait_for(
                    self._frames.get(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                if self.process is None or self.process.poll() is not None:
                    code = (
                        self.process.returncode
                        if self.process is not None
                        else "desconhecido"
                    )
                    raise RuntimeError(
                        f"A captura de áudio foi encerrada ({code})."
                    )

    async def stop(self):
        process = self.process

        if process is None:
            return

        loop = asyncio.get_running_loop()

        if process.poll() is None:
            try:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
            except OSError:
                pass

            deadline = loop.time() + 4
            while process.poll() is None and loop.time() < deadline:
                await asyncio.sleep(0.05)

            if process.poll() is None:
                process.terminate()

                deadline = loop.time() + 3
                while process.poll() is None and loop.time() < deadline:
                    await asyncio.sleep(0.05)

            if process.poll() is None:
                process.kill()

            # poll() confirmou que o processo terminou.
            if process.poll() is not None:
                process.wait()

        for thread in (self._stdout_thread, self._stderr_thread):
            if thread and thread.is_alive():
                deadline = loop.time() + 1.5

                while thread.is_alive() and loop.time() < deadline:
                    await asyncio.sleep(0.025)

                if not thread.is_alive():
                    thread.join()

        for stream in (
            process.stdin,
            process.stdout,
            process.stderr,
        ):
            try:
                if stream and not stream.closed:
                    stream.close()
            except OSError:
                pass

        self.process = None
        print("[LIVE AUDIO] Captura encerrada.")
