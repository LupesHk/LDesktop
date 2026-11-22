
import time
from pathlib import Path

from replay.audio_capture import AudioCapture

audio = AudioCapture()

try:
    print("Iniciando captura de áudio...")
    audio.start()

    print("Gravando por 15 segundos...")

    for remaining in range(15, 0, -1):
        print(f"Tempo restante: {remaining}s", end="\r")
        time.sleep(1)

    output = Path("data/replay/audio_test.wav")
    output.parent.mkdir(parents=True, exist_ok=True)

    audio.save_wav(output, duration=10)

    print("\nTeste concluído.")
    print(f"Arquivo: {output.resolve()}")

finally:
    audio.stop()
