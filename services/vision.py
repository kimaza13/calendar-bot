import base64
import requests
import json
from config import GROQ_API_KEY

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_PROMPT = """Ты помощник финансиста работающего в Южной Корее.
Извлеки все события с датами из изображения.
Верни ТОЛЬКО JSON без markdown:
{"events": [{"title": "название на русском", "date": "YYYY-MM-DD", "time": "HH:MM", "duration": 60, "notes": "заметка"}]}
Если событий нет - верни {"events": []}.
Для рейсов используй время вылета."""


def _compress_image(image_bytes: bytes, max_size: int = 3 * 1024 * 1024) -> bytes:
    """Сжимает изображение если оно больше max_size байт."""
    if len(image_bytes) <= max_size:
        return image_bytes
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        quality = 85
        while quality > 20:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality)
            if buffer.tell() <= max_size:
                return buffer.getvalue()
            quality -= 15
        return buffer.getvalue()
    except Exception:
        return image_bytes


def extract_events_from_image(image_bytes: bytes) -> list:
    image_bytes = _compress_image(image_bytes)
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    resp = requests.post(
        _GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": _PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                ]}
            ],
            "max_completion_tokens": 1000,
            "temperature": 0.1,
        },
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    raw = raw.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    return data.get("events", [])