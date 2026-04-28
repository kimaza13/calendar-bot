import base64
import json
import requests
from config import GOOGLE_SPEECH_API_KEY

_SPEECH_URL = "https://speech.googleapis.com/v1/speech:recognize"


def transcribe(audio_bytes: bytes) -> str:
    payload = {
        "config": {
            "encoding": "OGG_OPUS",
            "sampleRateHertz": 48000,
            "languageCode": "ru-RU",
        },
        "audio": {
            "content": base64.b64encode(audio_bytes).decode(),
        },
    }
    resp = requests.post(
        _SPEECH_URL,
        params={"key": GOOGLE_SPEECH_API_KEY},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        raise RuntimeError("Речь не распознана — попробуй ещё раз")
    return results[0]["alternatives"][0]["transcript"]
