import io
import speech_recognition as sr
from pydub import AudioSegment


def transcribe(audio_bytes: bytes) -> str:
    # Telegram sends voice as ogg/opus — convert to wav for SpeechRecognition
    ogg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="ogg")
    wav_io = io.BytesIO()
    ogg.export(wav_io, format="wav")
    wav_io.seek(0)

    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_io) as source:
        audio = recognizer.record(source)

    return recognizer.recognize_google(audio, language="ru-RU")
