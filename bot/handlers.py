from telegram import Update
from telegram.ext import ContextTypes
from services.parser import parse_event, parse_cancellation
from integrations.google_cal import find_events_by_title, delete_event
from services.sync import create_event_everywhere, list_all_events
from services.reminders import schedule_reminder
from services.transcribe import transcribe


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я помогу управлять твоим календарём.\n\n"
        "Просто напиши событие, например:\n"
        "  «Встреча с Алёной завтра в 15:00»\n\n"
        "Команды:\n"
        "/events — ближайшие события\n"
        "/help — помощь"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _process_text(update, context, update.message.text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_file = await context.bot.get_file(update.message.voice.file_id)
    audio_bytes = bytes(await tg_file.download_as_bytearray())
    try:
        text = transcribe(audio_bytes)
    except Exception as e:
        await update.message.reply_text(f"Не смог распознать голос: {e}")
        return
    await update.message.reply_text(f"Распознал: «{text}»")
    await _process_text(update, context, text)


async def _process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    cancel_title = parse_cancellation(text)
    if cancel_title is not None:
        await _cancel_event(update, cancel_title)
        return

    event = parse_event(text)
    if event is None:
        await update.message.reply_text(
            "Не смог распознать дату и время. Попробуй иначе, например: «Зубной врач в пятницу в 10:00»"
        )
        return

    await update.message.reply_text(
        f"Создаю событие «{event.title}» на {event.start.strftime('%d.%m.%Y %H:%M')}..."
    )
    results = create_event_everywhere(event.title, event.start, event.end)
    schedule_reminder(context.bot, update.effective_chat.id, event.title, event.start)

    icons = {"google": "🗓 Google", "apple": "🍎 Apple", "notion": "📝 Notion"}
    lines = [
        f"{'✅' if not str(v).startswith('error') else '❌'} {icons[k]}"
        for k, v in results.items()
    ]
    await update.message.reply_text("Готово!\n" + "\n".join(lines))


async def _cancel_event(update: Update, title: str):
    try:
        matches = find_events_by_title(title)
    except Exception as e:
        await update.message.reply_text(f"Ошибка при поиске события: {e}")
        return

    if not matches:
        await update.message.reply_text(f"Не нашёл предстоящих событий по запросу «{title}».")
        return

    # Delete the nearest match
    event = matches[0]
    event_title = event.get("summary", title)
    start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
    try:
        delete_event(event["id"])
    except Exception as e:
        await update.message.reply_text(f"Не смог удалить событие: {e}")
        return

    await update.message.reply_text(f"Событие «{event_title}» ({start[:16].replace('T', ' ')}) удалено из Google Calendar.")


async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    events = list_all_events()
    if not events:
        await update.message.reply_text("Ближайших событий не найдено.")
        return
    lines = []
    for e in events[:10]:
        start = e.get("start", "")
        if hasattr(start, "strftime"):
            start = start.strftime("%d.%m %H:%M")
        lines.append(f"• {e['title']} — {start} [{e.get('source', '')}]")
    await update.message.reply_text("\n".join(lines))
