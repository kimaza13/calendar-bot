# CLAUDE.md

## Project Overview
Telegram bot для управления Google Calendar. Flask + webhook на Render (Free plan).

## Stack
- Python 3.11, Flask (webhook, не polling)
- Groq API: llama-3.3-70b (текст/голос), llama-4-scout-17b-16e-instruct (vision/фото)
- Whisper via Groq: транскрипция голосовых
- Google Calendar API (OAuth2)
- Apple Calendar (CalDAV) — подключён но синхронизирован с Google, поэтому отключён из sync
- Notion — отключён
- dateparser для парсинга дат (Asia/Seoul timezone)
- SQLite (reminders.db) для напоминаний

## Структура
bot/handlers.py      — все handlers: text, voice, photo, commands
bot/api.py           — Telegram API calls
services/parser.py   — парсинг текста в ParsedEvent (Asia/Seoul)
services/reminder_parser.py  — парсинг повторяющихся напоминаний
services/reminders.py        — SQLite CRUD для напоминаний
services/scheduler.py        — фоновый поток, проверка напоминаний каждую минуту
services/planner.py          — AI план дня/недели через Groq
services/vision.py           — распознавание фото через Groq Vision (llama-4-scout)
services/sync.py             — create_event_everywhere (только google сейчас)
services/transcribe.py       — голос в текст через Groq Whisper
integrations/google_cal.py   — Google Calendar API
integrations/apple_cal.py    — CalDAV (подключён но не используется в sync)
integrations/notion_cal.py   — Notion (отключён)
main.py              — Flask app, webhook, init_db, start_scheduler, keep_alive

## Команды бота
- Текст/голос — создать событие (с подтверждением да/нет)
- Фото — распознать события через Groq Vision (с подтверждением)
- "Каждый месяц 25-го платёж Samsung в 14:00" — повторяющееся напоминание
- /plan, "план на сегодня" — AI план дня
- /week, "план на неделю" — AI план недели
- /events — ближайшие события из Google Calendar
- /reminders — список напоминаний
- /delreminder <id> — удалить напоминание
- "отмени встречу с командой" — удаление события (с подтверждением)

## Важные детали
- _pending_events dict — подтверждение перед созданием события
- _pending_deletions dict — подтверждение перед удалением
- При нескольких событиях на фото — бот показывает все но в _pending_events сохраняется только последнее (известная проблема)
- Keep-alive ping каждые 10 мин (Render Free засыпает)
- Scheduler в фоновом потоке — может остановиться если Render засыпает
- Часовой пояс: Asia/Seoul везде в parser.py

## Deploy
- GitHub kimaza13/calendar-bot — Render Auto-Deploy (branch: main)
- Env vars: TELEGRAM_BOT_TOKEN, GROQ_API_KEY, GOOGLE_TOKEN_JSON, WEBHOOK_URL, ICLOUD_USERNAME, ICLOUD_PASSWORD
- reminders.db хранится на Render — сбрасывается при редеплое

## Известные проблемы
- При нескольких событиях на фото сохраняется только последнее в _pending_events
- Слово "завтра" поздно вечером может давать +1 день (UTC vs Seoul)
