"""
services/planner.py

Берёт события из Google Calendar на день/неделю
и через Groq генерирует AI-план с приоритетами.
"""
from __future__ import annotations
import json
import requests
from datetime import date, timedelta
from config import GROQ_API_KEY
from integrations.google_cal import list_events

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM_PROMPT = """Ты AI-ассистент финансиста работающего в Южной Корее.
Тебе дают список событий из календаря на день или неделю.
Твоя задача — составить чёткий план с приоритетами.

Формат ответа:
- Сначала краткая сводка (1-2 предложения)
- Затем список задач по приоритету с временем
- В конце короткий совет на день

Будь конкретным и лаконичным. Отвечай на русском."""


def _format_events(events: list[dict]) -> str:
    if not events:
        return "Событий нет."
    lines = []
    for e in events:
        start = e.get("start", "")
        if hasattr(start, "strftime"):
            start = start.strftime("%d.%m %H:%M")
        lines.append(f"- {e['title']} в {start}")
    return "\n".join(lines)


def plan_day(target: date | None = None) -> str:
    if target is None:
        target = date.today()

    try:
        all_events = list_events()
    except Exception as e:
        return f"Не удалось получить события из календаря: {e}"

    # Фильтруем события на нужный день
    day_events = []
    for e in all_events:
        start = e.get("start")
        if hasattr(start, "date"):
            if start.date() == target:
                day_events.append(e)
        elif isinstance(start, str):
            if start.startswith(str(target)):
                day_events.append(e)

    date_str = target.strftime("%d.%m.%Y")

    if not day_events:
        return f"На {date_str} событий в календаре нет.\nДобавь события голосом или текстом, например: \"Встреча с бухгалтерией завтра в 10:00\""

    events_text = _format_events(day_events)

    prompt = f"""События на {date_str}:
{events_text}

Составь план дня для финансиста."""

    return _ask_groq(prompt)


def plan_week(start: date | None = None) -> str:
    if start is None:
        start = date.today()
    end = start + timedelta(days=6)

    try:
        all_events = list_events()
    except Exception as e:
        return f"Не удалось получить события из календаря: {e}"

    # Фильтруем события на неделю
    week_events = []
    for e in all_events:
        ev_start = e.get("start")
        ev_date = None
        if hasattr(ev_start, "date"):
            ev_date = ev_start.date()
        elif isinstance(ev_start, str) and len(ev_start) >= 10:
            try:
                from datetime import datetime
                ev_date = datetime.fromisoformat(ev_start[:10]).date()
            except Exception:
                pass
        if ev_date and start <= ev_date <= end:
            week_events.append(e)

    period = f"{start.strftime('%d.%m')} – {end.strftime('%d.%m.%Y')}"

    if not week_events:
        return f"На неделю ({period}) событий в календаре нет.\nДобавь события голосом или текстом, например: \"Платёж поставщику в пятницу в 14:00\""

    events_text = _format_events(week_events)

    prompt = f"""События на неделю ({period}):
{events_text}

Составь план недели для финансиста с приоритетами по дням."""

    return _ask_groq(prompt)


def _ask_groq(user_prompt: str) -> str:
    try:
        resp = requests.post(
            _GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 800,
                "temperature": 0.7,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Ошибка AI-планирования: {e}"
