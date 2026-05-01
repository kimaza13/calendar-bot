from bot import api as tg
from services.parser import parse_event, parse_cancellation
from services.reminder_parser import parse_reminder
from services.reminders import add_reminder, list_reminders, delete_reminder
from integrations.google_cal import find_events_by_title, delete_event
from services.sync import create_event_everywhere, list_all_events
from services.transcribe import transcribe
from services.planner import plan_day, plan_week

# Хранилище событий ожидающих подтверждения: {chat_id: ParsedEvent}
_pending_events: dict = {}



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
        elif text.startswith("/reminders"):
            _cmd_reminders(chat_id)
        elif text.startswith("/plan"):
            _cmd_plan(chat_id)
        elif text.startswith("/week"):
            _cmd_week(chat_id)
        elif text.startswith("/delreminder"):
            _cmd_del_reminder(chat_id, text)
        else:
            _process_text(chat_id, text)
    elif "voice" in message:
        _handle_voice(chat_id, message["voice"])


def _cmd_start(chat_id: int) -> None:
    tg.send_message(chat_id,
        "Привет! Я помогу управлять твоим календарём.\n\n"
        "Напиши или надиктуй событие, например:\n"
        "  «Встреча с Алёной завтра в 15:00»\n\n"
        "Повторяющиеся напоминания:\n"
        "  «Каждый месяц 25-го платёж CJ Logistics в 14:00»\n"
        "  «Напоминай за 5 дней платёж Samsung 20-го числа»\n\n"
        "Команды:\n"
        "/events — ближайшие события\n"
        "/reminders — мои напоминания\n"
        "/delreminder <id> — удалить напоминание\n"
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
    # Проверяем — это команда напоминания?
    reminder = parse_reminder(text)
    if reminder is not None:
        _add_reminder(chat_id, reminder)
        return

    # Проверяем — это отмена события?
    low = text.lower().strip()

    # Обработка подтверждения события
    if chat_id in _pending_events:
        if low in ("да", "yes", "✅", "ок", "ok", "создать", "подтвердить"):
            _confirm_event(chat_id)
            return
        elif low in ("нет", "no", "❌", "отмена", "отменить", "cancel"):
            _pending_events.pop(chat_id, None)
            tg.send_message(chat_id, "Отменено.")
            return

    if "план на сегодня" in low or "план дня" in low:
        _cmd_plan(chat_id)
        return
    if "план на неделю" in low or "план недели" in low:
        _cmd_week(chat_id)
        return

    cancel_title = parse_cancellation(text)
    if cancel_title is not None:
        _cancel_event(chat_id, cancel_title)
        return

    # Обычное событие
    event = parse_event(text)
    if event is None:
        tg.send_message(
            chat_id,
            "Не смог распознать дату и время. Попробуй иначе, например:\n"
            "  «Зубной врач в пятницу в 10:00»\n"
            "  «Каждый месяц 25-го платёж Samsung в 14:00»"
        )
        return

    print(f"BEFORE CREATE: start={event.start}, tzinfo={event.start.tzinfo}")
    _pending_events[chat_id] = event
    tg.send_message(
        chat_id,
        f"Распознал: «{event.title}»\n"
        f"📅 {event.start.strftime('%d.%m.%Y')} в {event.start.strftime('%H:%M')}\n\n"
        f"Создать событие в календаре? (да / нет)"
    )


def _add_reminder(chat_id: int, reminder) -> None:
    try:
        rid = add_reminder(
            chat_id=chat_id,
            title=reminder.title,
            day_of_month=reminder.day_of_month,
            remind_days=reminder.remind_days,
            hour=reminder.hour,
            minute=reminder.minute,
        )
        tg.send_message(
            chat_id,
            f"✅ Напоминание добавлено (ID: {rid})\n"
            f"📌 «{reminder.title}»\n"
            f"📅 Каждое {reminder.day_of_month}-е число в {reminder.hour:02d}:{reminder.minute:02d}\n"
            f"⏰ Напомню за {reminder.remind_days} дн. до события"
        )
    except Exception as e:
        tg.send_message(chat_id, f"Ошибка при сохранении напоминания: {e}")



def _confirm_event(chat_id: int) -> None:
    event = _pending_events.pop(chat_id, None)
    if event is None:
        tg.send_message(chat_id, "Нет события для создания.")
        return
    tg.send_message(chat_id, f"Создаю «{event.title}»...")
    results = create_event_everywhere(event.title, event.start, event.end)
    lines = []
    for k, v in {k: v for k, v in results.items() if k != "notion"}.items():
        s = str(v)
        icons = {"google": "🗓 Google", "apple": "🍎 Apple"}
        if s.startswith("error:"):
            lines.append(f"❌ {icons.get(k, k)}: {s[7:]}")
        else:
            lines.append(f"✅ {icons.get(k, k)}")
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


def _cmd_reminders(chat_id: int) -> None:
    rows = list_reminders(chat_id)
    if not rows:
        tg.send_message(
            chat_id,
            "У тебя нет активных напоминаний.\n\n"
            "Добавь: «Каждый месяц 25-го платёж Samsung в 14:00»"
        )
        return
    lines = ["📋 Твои напоминания:\n"]
    for r in rows:
        lines.append(
            f"[{r['id']}] «{r['title']}»\n"
            f"    📅 {r['day_of_month']}-е число в {r['hour']:02d}:{r['minute']:02d} "
            f"(напомню за {r['remind_days']} дн.)"
        )
    lines.append("\nУдалить: /delreminder <id>")
    tg.send_message(chat_id, "\n".join(lines))


def _cmd_del_reminder(chat_id: int, text: str) -> None:
    parts = text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        tg.send_message(chat_id, "Укажи ID: /delreminder 3")
        return
    rid = int(parts[1])
    if delete_reminder(rid, chat_id):
        tg.send_message(chat_id, f"✅ Напоминание #{rid} удалено.")
    else:
        tg.send_message(chat_id, f"Напоминание #{rid} не найдено.")


def _cmd_plan(chat_id: int) -> None:
    tg.send_message(chat_id, "Составляю план на сегодня...")
    result = plan_day()
    tg.send_message(chat_id, result)


def _cmd_week(chat_id: int) -> None:
    tg.send_message(chat_id, "Составляю план на неделю...")
    result = plan_week()
    tg.send_message(chat_id, result)
