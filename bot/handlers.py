from bot import api as tg
from services.parser import parse_event, parse_cancellation
from services.reminder_parser import parse_reminder
from services.reminders import add_reminder, list_reminders, delete_reminder
from integrations.google_cal import find_events_by_title, delete_event
from services.sync import create_event_everywhere, list_all_events
from services.transcribe import transcribe
from services.planner import plan_day, plan_week
from services.vision import extract_events_from_image

# Хранилище событий ожидающих подтверждения: {chat_id: [ParsedEvent]}
_pending_events: dict = {}
# Хранилище событий ожидающих удаления: {chat_id: event_dict}
_pending_deletions: dict = {}


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
    elif 'photo' in message:
        _handle_photo(chat_id, message['photo'])


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


def _format_event(event) -> str:
    """Форматирует событие для отображения."""
    return (
        f"📌 {event.title}\n"
        f"📅 {event.start.strftime('%d.%m.%Y')} в {event.start.strftime('%H:%M')}"
    )


def _send_pending_event(chat_id: int, event) -> None:
    """Показывает событие и подсказку по редактированию."""
    tg.send_message(
        chat_id,
        _format_event(event) + "\n\n"
        "Создать? (да / нет)\n"
        "Или отредактируй:\n"
        "  название Встреча с Иваном\n"
        "  время 16:00\n"
        "  дата 15.05"
    )


def _handle_photo(chat_id: int, photos: list) -> None:
    try:
        best = max(photos, key=lambda p: p.get('file_size', 0))
        image_bytes = tg.get_file_bytes(best['file_id'])
        tg.send_message(chat_id, 'Анализирую изображение...')
        events = extract_events_from_image(image_bytes)
    except Exception as e:
        tg.send_message(chat_id, f'Не смог обработать фото: {e}')
        return
    if not events:
        tg.send_message(chat_id, 'Не нашёл событий с датами на этом изображении.')
        return

    parsed = []
    failed = []
    for evt in events:
        from datetime import datetime, timedelta
        try:
            dt = datetime.strptime(f"{evt['date']} {evt['time']}", '%Y-%m-%d %H:%M')
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo('Asia/Tashkent'))
        except Exception:
            failed.append(evt.get('title', '?'))
            continue
        from services.parser import ParsedEvent
        event = ParsedEvent(title=evt['title'], start=dt, end=dt + timedelta(minutes=evt.get('duration', 60)))
        parsed.append(event)

    if failed:
        tg.send_message(chat_id, 'Не смог разобрать дату у: ' + ', '.join(f'«{t}»' for t in failed))

    if not parsed:
        return

    _pending_events[chat_id] = parsed
    _show_all_pending(chat_id)


def _show_all_pending(chat_id: int) -> None:
    events = _pending_events[chat_id]
    lines = [f'Нашёл {len(events)} событий(я):\n']
    for i, e in enumerate(events, 1):
        lines.append(f'{i}. {e.title} — {e.start.strftime("%d.%m.%Y")} в {e.start.strftime("%H:%M")}')
    lines.append('\nВведи номера через запятую (например: 1,3)\nили "все" чтобы создать все, "нет" чтобы отменить')
    tg.send_message(chat_id, '\n'.join(lines))


def _handle_voice(chat_id: int, voice: dict) -> None:
    try:
        audio_bytes = tg.get_file_bytes(voice["file_id"])
        text = transcribe(audio_bytes)
    except Exception as e:
        tg.send_message(chat_id, f"Не смог распознать голос: {e}")
        return
    tg.send_message(chat_id, f"Распознал: «{text}»")
    _process_text(chat_id, text)


def _parse_numbers(text: str) -> list:
    """Парсит '1,3' или '1 3' или '1, 3' в список чисел."""
    import re
    nums = re.findall(r'\d+', text)
    return [int(n) for n in nums] if nums else []


def _try_edit_event(chat_id: int, text: str) -> bool:
    """
    Пытается применить правку к событию в очереди.
    Возвращает True если правка распознана, False если нет.
    Форматы:
      название <новое название>
      время <ЧЧ:ММ>
      дата <ДД.ММ> или <ДД.ММ.ГГГГ>
    """
    import re
    from datetime import datetime, timedelta

    if not _pending_events.get(chat_id):
        return False

    event = _pending_events[chat_id][0]
    low = text.lower().strip()

    # Редактирование названия
    if low.startswith("название "):
        new_title = text[len("название "):].strip()
        if new_title:
            from services.parser import ParsedEvent
            _pending_events[chat_id][0] = ParsedEvent(
                title=new_title,
                start=event.start,
                end=event.end
            )
            _send_pending_event(chat_id, _pending_events[chat_id][0])
            return True

    # Редактирование времени
    if low.startswith("время "):
        time_str = low[len("время "):].strip()
        m = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
        if m:
            from zoneinfo import ZoneInfo
            from services.parser import ParsedEvent
            new_start = event.start.replace(hour=int(m.group(1)), minute=int(m.group(2)))
            duration = event.end - event.start
            _pending_events[chat_id][0] = ParsedEvent(
                title=event.title,
                start=new_start,
                end=new_start + duration
            )
            _send_pending_event(chat_id, _pending_events[chat_id][0])
            return True

    # Редактирование даты
    if low.startswith("дата "):
        date_str = low[len("дата "):].strip()
        # Формат ДД.ММ или ДД.ММ.ГГГГ
        m = re.match(r'^(\d{1,2})\.(\d{2})(?:\.(\d{4}))?$', date_str)
        if m:
            from services.parser import ParsedEvent
            day = int(m.group(1))
            month = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else event.start.year
            new_start = event.start.replace(day=day, month=month, year=year)
            duration = event.end - event.start
            _pending_events[chat_id][0] = ParsedEvent(
                title=event.title,
                start=new_start,
                end=new_start + duration
            )
            _send_pending_event(chat_id, _pending_events[chat_id][0])
            return True

    return False


def _create_events_batch(chat_id: int, events: list) -> None:
    """Создаёт несколько событий подряд и отправляет итог."""
    tg.send_message(chat_id, f'Создаю {len(events)} событий(я)...')
    for event in events:
        results = create_event_everywhere(event.title, event.start, event.end)
        lines = [f'«{event.title}»']
        for k, v in {k: v for k, v in results.items() if k != "notion"}.items():
            s = str(v)
            icons = {"google": "🗓 Google", "apple": "🍎 Apple"}
            if s.startswith("error:"):
                lines.append(f"  ❌ {icons.get(k, k)}: {s[7:]}")
            else:
                lines.append(f"  ✅ {icons.get(k, k)}")
        tg.send_message(chat_id, '\n'.join(lines))
    tg.send_message(chat_id, '✅ Готово!')


def _process_text(chat_id: int, text: str) -> None:
    reminder = parse_reminder(text)
    if reminder is not None:
        _add_reminder(chat_id, reminder)
        return

    low = text.lower().strip()

    # Обработка подтверждения удаления
    if chat_id in _pending_deletions:
        if low in ("да", "yes", "✅", "ок", "ok", "удалить", "подтвердить"):
            _confirm_deletion(chat_id)
            return
        elif low in ("нет", "no", "❌", "отмена", "отменить", "cancel"):
            _pending_deletions.pop(chat_id, None)
            tg.send_message(chat_id, "Удаление отменено.")
            return

    # Обработка выбора событий из фото (список из нескольких)
    if chat_id in _pending_events and isinstance(_pending_events[chat_id], list) and len(_pending_events[chat_id]) > 1:
        if low in ("все", "all", "создать все", "добавить все"):
            events = _pending_events.pop(chat_id)
            _create_events_batch(chat_id, events)
            return
        elif low in ("нет", "no", "❌", "отмена", "отменить", "cancel"):
            _pending_events.pop(chat_id, None)
            tg.send_message(chat_id, "Отменено.")
            return
        else:
            indices = _parse_numbers(low)
            if indices:
                events = _pending_events.pop(chat_id)
                chosen = [events[i - 1] for i in indices if 1 <= i <= len(events)]
                if chosen:
                    _create_events_batch(chat_id, chosen)
                else:
                    tg.send_message(chat_id, "Не понял номера. Попробуй ещё раз.")
                    _pending_events[chat_id] = events
                return

    # Обработка одиночного события (с возможностью редактирования)
    if chat_id in _pending_events and _pending_events[chat_id]:
        if low in ("да", "yes", "✅", "ок", "ok", "создать", "подтвердить"):
            _confirm_event(chat_id)
            return
        elif low in ("нет", "no", "❌", "отмена", "отменить", "cancel"):
            _pending_events.pop(chat_id, None)
            tg.send_message(chat_id, "Отменено.")
            return
        # Пробуем применить правку
        elif _try_edit_event(chat_id, text):
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
    if chat_id not in _pending_events:
        _pending_events[chat_id] = []
    _pending_events[chat_id].append(event)
    _send_pending_event(chat_id, event)


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


def _confirm_deletion(chat_id: int) -> None:
    event = _pending_deletions.pop(chat_id, None)
    if event is None:
        tg.send_message(chat_id, "Нет события для удаления.")
        return
    event_title = event.get("summary", "")
    try:
        delete_event(event["id"])
        tg.send_message(chat_id, f"✅ Событие «{event_title}» удалено из Google Calendar.")
    except Exception as e:
        tg.send_message(chat_id, f"Не смог удалить событие: {e}")


def _confirm_event(chat_id: int) -> None:
    if not _pending_events.get(chat_id):
        tg.send_message(chat_id, "Нет события для создания.")
        return
    event = _pending_events[chat_id].pop(0)
    if not _pending_events[chat_id]:
        _pending_events.pop(chat_id)
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
    start_str = start[:16].replace("T", " ") if start else ""
    _pending_deletions[chat_id] = event
    tg.send_message(
        chat_id,
        f"Найдено событие: «{event_title}»\n"
        f"📅 {start_str}\n\n"
        f"Удалить из Google Calendar? (да / нет)"
    )


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
