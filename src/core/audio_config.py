
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd

from core.paths import DATA_DIR, LOG_DIR


AUDIO_SETTINGS_FILE = DATA_DIR / "audio_settings.json"
AUDIO_LOG_FILE = LOG_DIR / "audio.log"

SAMPLE_RATE = 48000
TEST_DURATION_SECONDS = 2
TEST_CHUNK_SECONDS = 0.10
BLOCKSIZE_SECONDS = 0.20


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
        print(f"[AUDIO LOG] Erro ao registrar: {log_error}")


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


def _get_hostapi_names():
    return [
        str(hostapi["name"])
        for hostapi in sd.query_hostapis()
    ]


def _device_id(hostapi_name, device_name):
    return f"{hostapi_name}::{device_name}"


def list_microphones():
    """Lista dispositivos de entrada disponíveis no SoundDevice."""
    devices = sd.query_devices()
    hostapi_names = _get_hostapi_names()

    result = []

    for index, device in enumerate(devices):
        channels = int(device["max_input_channels"])

        if channels <= 0:
            continue

        hostapi_index = int(device["hostapi"])
        hostapi_name = hostapi_names[hostapi_index]
        device_name = str(device["name"])

        result.append({
            "id": _device_id(hostapi_name, device_name),
            "index": index,
            "name": device_name,
            "hostapi": hostapi_name,
            "channels": channels,
            "samplerate": float(device["default_samplerate"]),
        })

    # Prioriza WASAPI, mantendo as demais APIs como alternativas.
    result.sort(
        key=lambda item: (
            0 if item["hostapi"] == "Windows WASAPI" else 1,
            item["name"].casefold(),
            item["hostapi"].casefold(),
        )
    )

    return result



def get_default_microphone_info():
    devices = list_microphones()

    if not devices:
        raise RuntimeError(
            "Nenhum dispositivo de entrada foi encontrado."
        )

    default_name = None

    try:
        default_index = sd.default.device[0]

        if default_index is not None and int(default_index) >= 0:
            default_device = sd.query_devices(int(default_index))
            default_name = str(default_device["name"])

    except Exception:
        pass

    # Prioriza WASAPI correspondente ao microfone padrão do Windows.
    if default_name:
        for device in devices:
            if (
                device["hostapi"] == "Windows WASAPI"
                and device["name"] == default_name
            ):
                return device

    # Se não encontrar correspondência, prioriza qualquer WASAPI.
    for device in devices:
        if device["hostapi"] == "Windows WASAPI":
            return device

    return devices[0]


def resolve_microphone(microphone_id=None):
    """Resolve o índice atual usando o identificador persistente."""
    devices = list_microphones()

    if not devices:
        raise RuntimeError(
            "Nenhum microfone disponível foi encontrado."
        )

    if microphone_id is None:
        return get_default_microphone_info()

    requested_id = str(microphone_id)

    for device in devices:
        if device["id"] == requested_id:
            return device

    raise RuntimeError(
        "O microfone selecionado não está disponível. "
        "Atualize a lista de dispositivos ou selecione outro."
    )


def _get_input_stream_settings(device):
    if device["hostapi"] == "Windows WASAPI":
        return sd.WasapiSettings(auto_convert=True)

    return None


def test_microphone(microphone_id=None):
    """
    Testa o microfone com SoundDevice.
    Nenhum áudio do teste é salvo em disco.
    """
    microphone = resolve_microphone(microphone_id)

    frames = int(SAMPLE_RATE * TEST_CHUNK_SECONDS)
    blocksize = int(SAMPLE_RATE * BLOCKSIZE_SECONDS)

    chunks = []

    with sd.InputStream(
        device=microphone["index"],
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=blocksize,
        extra_settings=_get_input_stream_settings(microphone),
    ) as stream:

        total_chunks = int(
            TEST_DURATION_SECONDS / TEST_CHUNK_SECONDS
        )

        for _ in range(total_chunks):
            audio, overflowed = stream.read(frames)

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
        "device_name": microphone["name"],
        "hostapi": microphone["hostapi"],
        "peak": peak,
        "rms": rms,
        "peak_dbfs": peak_dbfs,
        "rms_dbfs": rms_dbfs,
        "signal_detected": peak >= 0.003 and rms >= 0.0003,
    }
