import requests
from config import TELEGRAM_BOT_TOKEN

_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(chat_id: int, text: str) -> None:
    requests.post(f"{_BASE}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)


def send_keyboard(chat_id: int, text: str, keyboard: list) -> None:
    requests.post(
        f"{_BASE}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {"inline_keyboard": keyboard},
        },
        timeout=10,
    )


def answer_callback(callback_id: str) -> None:
    requests.post(f"{_BASE}/answerCallbackQuery", json={"callback_query_id": callback_id}, timeout=10)


def get_file_bytes(file_id: str) -> bytes:
    r = requests.get(f"{_BASE}/getFile", params={"file_id": file_id}, timeout=10)
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]
    r2 = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}", timeout=30)
    r2.raise_for_status()
    return r2.content


def set_webhook(url: str) -> None:
    requests.post(f"{_BASE}/setWebhook", json={"url": url}, timeout=10)
