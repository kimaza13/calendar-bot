from bot import api as tg
from services.parser import parse_event, parse_cancellation
from integrations.google_cal import find_events_by_title, delete_event
from services.sync import create_event_everywhere, list_all_events
from services.transcribe import transcribe


def handle_update(update: dict) -> None:
    message = update.get("message", {})
    if not message:
        return
    chat_id = message["chat"]["id"]
    if "text" in message:
        text = message["text"]
        if text.startswith("/start") or text.startswith("/help"):
            _cmd_start(chat_id)
        elif text.startswith("/events"):
            _cmd_events(chat_id)
        else:
            _process_text(chat_id, text)
    elif "voice" in message:
        _handle_voice(chat_id, message["voice"])


def _cmd_start(chat_id: int) -> None:
    tg.send_message(chat_id,
        "Привет! Я помогу управлять твоим календарём.\n\n"
        "Напиши или надиктуй событие, например:\n"
        "  «Встреча с Алёной завтра в 15:00»\n\n"
        "Команды:\n"
        "/events — ближайшие события\n"
        "/help — помощь"
    )


def _handle_voice(chat_id: int, voice: dict) -> None:
    try:
        audio_bytes = tg.get_file_bytes(voice["file_id"])
        text = transcribe(audio_bytes)
    except Exception as e:
        tg.send_message(chat_id, f"Не смог распознать голос: {e}")
        return
    tg.send_message(chat_id, f"Распознал: «{text}»")
    _process_text(chat_id, text)


def _process_text(chat_id: int, text: str) -> None:
    cancel_title = parse_cancellation(text)
    if cancel_title is not None:
        _cancel_event(chat_id, cancel_title)
        return

    event = parse_event(text)
    if event is None:
        tg.send_message(chat_id, "Не смог распознать дату и время. Попробуй иначе, например: «Зубной врач в пятницу в 10:00»")
        return

    tg.send_message(chat_id, f"Создаю событие «{event.title}» на {event.start.strftime('%d.%m.%Y %H:%M')}...")
    results = create_event_everywhere(event.title, event.start, event.end)

    icons = {"google": "🗓 Google", "apple": "🍎 Apple", "notion": "📝 Notion"}
    lines = [
        f"{'✅' if not str(v).startswith('error') else '❌'} {icons[k]}"
        for k, v in results.items()
    ]
    tg.send_message(chat_id, "Готово!\n" + "\n".join(lines))


def _cancel_event(chat_id: int, title: str) -> None:
    try:
        matches = find_events_by_title(title)
    except Exception as e:
        tg.send_message(chat_id, f"Ошибка при поиске события: {e}")
        return

    if not matches:
        tg.send_message(chat_id, f"Не нашёл предстоящих событий по запросу «{title}».")
        return

    event = matches[0]
    event_title = event.get("summary", title)
    start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
    try:
        delete_event(event["id"])
    except Exception as e:
        tg.send_message(chat_id, f"Не смог удалить событие: {e}")
        return

    tg.send_message(chat_id, f"Событие «{event_title}» ({start[:16].replace('T', ' ')}) удалено из Google Calendar.")


def _cmd_events(chat_id: int) -> None:
    events = list_all_events()
    if not events:
        tg.send_message(chat_id, "Ближайших событий не найдено.")
        return
    lines = []
    for e in events[:10]:
        start = e.get("start", "")
        if hasattr(start, "strftime"):
            start = start.strftime("%d.%m %H:%M")
        lines.append(f"• {e['title']} — {start} [{e.get('source', '')}]")
    tg.send_message(chat_id, "\n".join(lines))
