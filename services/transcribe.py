import io
import re
import requests
from config import GROQ_API_KEY

_GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def _looks_like_misdetection(text: str) -> bool:
    """True if Whisper returned mostly Latin text — likely wrong language detected."""
    if not text or len(text) < 5:
        return False
    latin = len(re.findall(r"[a-zA-Z]", text))
    non_latin = len(re.findall(r"[Ѐ-ӿ가-힯一-鿿]", text))
    return latin > 5 and non_latin == 0


def _call_whisper(audio_bytes: bytes, language: str | None = None) -> str:
    data: dict = {"model": "whisper-large-v3"}
    if language:
        data["language"] = language
    resp = requests.post(
        _GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files={"file": ("voice.ogg", io.BytesIO(audio_bytes), "audio/ogg")},
        data=data,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["text"]


def transcribe(audio_bytes: bytes) -> str:
    text = _call_whisper(audio_bytes)
    # If auto-detection returned Latin text (e.g. Polish instead of Russian), retry with ru
    if _looks_like_misdetection(text):
        text = _call_whisper(audio_bytes, language="ru")
    return text
