import json
import os
import subprocess
import tempfile
import urllib.request

# Free Google Web Speech API used by chromium-based clients
_GOOGLE_SPEECH_URL = (
    "https://www.google.com/speech-api/v2/recognize"
    "?client=chromium&lang=ru-RU"
    "&key=AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"
)


def transcribe(audio_bytes: bytes) -> str:
    wav_bytes = _ogg_to_wav(audio_bytes)
    return _recognize(wav_bytes)


def _ogg_to_wav(audio_bytes: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(audio_bytes)
        ogg_path = f.name
    wav_path = ogg_path[:-4] + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", ogg_path, "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", wav_path],
            check=True,
            capture_output=True,
        )
        with open(wav_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(ogg_path)
        if os.path.exists(wav_path):
            os.unlink(wav_path)


def _recognize(wav_bytes: bytes) -> str:
    req = urllib.request.Request(
        _GOOGLE_SPEECH_URL,
        data=wav_bytes,
        headers={"Content-Type": "audio/x-wav; rate=16000"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        for line in resp.read().decode().splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            for result in data.get("result", []):
                alternatives = result.get("alternative", [])
                if alternatives:
                    return alternatives[0]["transcript"]
    raise RuntimeError("Речь не распознана — попробуй ещё раз")
