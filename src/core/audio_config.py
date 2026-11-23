
import json
import math
from pathlib import Path

import numpy as np
import soundcard as sc

from core.paths import DATA_DIR, LOG_DIR
from datetime import datetime


AUDIO_SETTINGS_FILE = DATA_DIR / "audio_settings.json"

AUDIO_LOG_FILE = LOG_DIR / "audio.log"


def log_audio_error(context, error, traceback_text):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )

        with AUDIO_LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(f"\n{'=' * 70}\n")
            file.write(f"Data: {timestamp}\n")
            file.write(f"Contexto: {context}\n")
            file.write(
                f"Erro: {type(error).__name__}: {error}\n\n"
            )
            file.write(traceback_text)
            file.write("\n")

    except Exception as log_error:
        print(f"[AUDIO LOG] Não foi possível registrar o erro: {log_error}")

SAMPLE_RATE = 48000
TEST_DURATION_SECONDS = 2
TEST_CHUNK_SECONDS = 0.10
BLOCKSIZE_SECONDS = 0.20


def load_audio_settings():
    default_settings = {
        "microphone_id": None,
        "microphone_name": "Padrão do Windows",
    }

    try:
        with AUDIO_SETTINGS_FILE.open("r", encoding="utf-8") as file:
            settings = json.load(file)

        if not isinstance(settings, dict):
            return default_settings

        microphone_id = settings.get("microphone_id")
        microphone_name = settings.get("microphone_name")

        return {
            "microphone_id": (
                str(microphone_id)
                if microphone_id is not None
                else None
            ),
            "microphone_name": (
                str(microphone_name)
                if microphone_name
                else "Padrão do Windows"
            ),
        }

    except FileNotFoundError:
        return default_settings

    except Exception as error:
        print(f"[AUDIO CONFIG] Erro ao ler preferências: {error}")
        return default_settings


def save_audio_settings(microphone_id, microphone_name):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    settings = {
        "microphone_id": (
            str(microphone_id)
            if microphone_id is not None
            else None
        ),
        "microphone_name": str(microphone_name),
    }

    temporary_file = AUDIO_SETTINGS_FILE.with_suffix(".json.tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(
            settings,
            file,
            ensure_ascii=False,
            indent=4,
        )

    temporary_file.replace(AUDIO_SETTINGS_FILE)

    print(
        f"[AUDIO CONFIG] Preferência salva: "
        f"{settings['microphone_name']}"
    )


def get_default_microphone_info():
    microphone = sc.default_microphone()

    return {
        "id": str(microphone.id),
        "name": str(microphone.name),
    }


def list_microphones():
    """Lista somente entradas de microfone, sem loopbacks."""
    devices = sc.all_microphones(include_loopback=False)

    result = []
    seen_ids = set()

    for device in devices:
        if getattr(device, "isloopback", False):
            continue

        device_id = str(device.id)

        if device_id in seen_ids:
            continue

        seen_ids.add(device_id)

        channels = device.channels

        channel_count = (
            channels
            if isinstance(channels, int)
            else len(channels)
        )

        result.append({
            "id": device_id,
            "name": str(device.name),
            "channels": channel_count,
        })

    return sorted(
        result,
        key=lambda item: item["name"].casefold(),
    )


def resolve_microphone(microphone_id=None):
    """Resolve o dispositivo pelo ID exato ou usa o padrão do Windows."""
    if microphone_id is None:
        return sc.default_microphone()

    requested_id = str(microphone_id)

    for microphone in sc.all_microphones(include_loopback=False):
        if str(microphone.id) == requested_id:
            return microphone

    raise RuntimeError(
        "O microfone selecionado não está disponível. "
        "Atualize a lista de dispositivos ou selecione outro."
    )


def test_microphone(microphone_id=None):
    """
    Abre o dispositivo e captura amostras temporárias.
    Nenhum áudio do teste é salvo em disco.
    """
    microphone = resolve_microphone(microphone_id)

    frames = int(SAMPLE_RATE * TEST_CHUNK_SECONDS)
    blocksize = int(SAMPLE_RATE * BLOCKSIZE_SECONDS)

    chunks = []

    with microphone.recorder(
        samplerate=SAMPLE_RATE,
        channels=1,
        blocksize=blocksize,
    ) as recorder:

        total_chunks = int(
            TEST_DURATION_SECONDS / TEST_CHUNK_SECONDS
        )

        for _ in range(total_chunks):
            audio = recorder.record(numframes=frames)

            if len(audio):
                chunks.append(
                    np.asarray(audio, dtype=np.float32)
                )

    if not chunks:
        raise RuntimeError(
            "O dispositivo abriu, mas não entregou amostras de áudio."
        )

    samples = np.concatenate(chunks, axis=0)
    samples = np.nan_to_num(samples)

    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(np.square(samples))))

    peak_dbfs = 20 * math.log10(max(peak, 1e-8))
    rms_dbfs = 20 * math.log10(max(rms, 1e-8))

    return {
        "device_name": str(microphone.name),
        "peak": peak,
        "rms": rms,
        "peak_dbfs": peak_dbfs,
        "rms_dbfs": rms_dbfs,
        "signal_detected": peak >= 0.003 and rms >= 0.0003,
    }
