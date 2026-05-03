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


def extract_events_from_image(image_bytes: bytes) -> list:
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    resp = requests.post(
        _GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "llama-3.2-11b-vision-preview",
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": _PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                ]}
            ],
            "max_tokens": 1000,
            "temperature": 0.1,
        },
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    raw = raw.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    return data.get("events", [])