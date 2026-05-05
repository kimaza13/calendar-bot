import io
import requests
from config import GROQ_API_KEY

_GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def transcribe(audio_bytes: bytes) -> str:
    resp = requests.post(
        _GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files={"file": ("voice.ogg", io.BytesIO(audio_bytes), "audio/ogg")},
        data={"model": "whisper-large-v3-turbo", "language": "ru"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["text"]
