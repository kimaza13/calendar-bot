import io
import json
import urllib.request
import wave

import av

# Free Google Web Speech API used by Chromium
_GOOGLE_SPEECH_URL = (
    "https://www.google.com/speech-api/v2/recognize"
    "?client=chromium&lang=ru-RU"
    "&key=AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"
)


def transcribe(audio_bytes: bytes) -> str:
    wav_bytes = _ogg_to_wav(audio_bytes)
    return _recognize(wav_bytes)


def _ogg_to_wav(audio_bytes: bytes) -> bytes:
    container = av.open(io.BytesIO(audio_bytes))
    audio_stream = next(s for s in container.streams if s.type == "audio")

    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    pcm_chunks = []
    for frame in container.decode(audio_stream):
        for rf in resampler.resample(frame):
            pcm_chunks.append(bytes(rf.planes[0]))
    for rf in resampler.resample(None):  # flush
        pcm_chunks.append(bytes(rf.planes[0]))

    pcm = b"".join(pcm_chunks)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(16000)
        wf.writeframes(pcm)
    return buf.getvalue()


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
