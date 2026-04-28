from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import re
import dateparser.search


@dataclass
class ParsedEvent:
    title: str
    start: datetime
    end: datetime


# "7 вечера" → "19:00", "10 утра" → "10:00", etc.
_TIME_OF_DAY = {
    "ночи":   (0,  6),   # 1 ночи → 01:00
    "утра":   (0,  11),  # 10 утра → 10:00
    "дня":    (12, 17),  # 3 дня → 15:00
    "вечера": (12, 23),  # 7 вечера → 19:00
}

_TOD_PATTERN = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s+(ночи|утра|дня|вечера)\b", re.IGNORECASE
)


def _normalize_time_of_day(text: str) -> str:
    def replace(m: re.Match) -> str:
        hour = int(m.group(1))
        minutes = m.group(2) or "00"
        period = m.group(3).lower()
        low, high = _TIME_OF_DAY[period]
        if hour < 12 and low >= 12:
            hour += 12
        elif hour == 12 and low == 0:
            hour = 0
        return f"{hour:02d}:{minutes}"
    return _TOD_PATTERN.sub(replace, text)


_CANCEL_WORDS = re.compile(
    r"^(отмени|отменить|отмена|отменяй|удали|удалить|убери|убрать|cancel|delete)\s+",
    re.IGNORECASE,
)


def parse_cancellation(text: str) -> Optional[str]:
    """Return the event title to cancel, or None if not a cancellation request."""
    m = _CANCEL_WORDS.match(text.strip())
    if not m:
        return None
    return text.strip()[m.end():].strip() or None


def parse_event(text: str) -> Optional[ParsedEvent]:
    normalized = _normalize_time_of_day(text)
    results = dateparser.search.search_dates(
        normalized,
        languages=["ru", "en"],
        settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": True},
    )
    if not results:
        return None

    date_str, dt = results[0]
    dt = _ensure_future(dt)
    title = _extract_title(normalized, date_str) or "Событие"
    return ParsedEvent(title=title, start=dt, end=dt + timedelta(hours=1))


def _ensure_future(dt: datetime) -> datetime:
    now = datetime.now(tz=dt.tzinfo)
    # Compare by date only: if the date itself is in the past, advance by weeks.
    # Avoids bumping "сегодня" (midnight) into next week just because time passed.
    while dt.date() < now.date():
        dt += timedelta(days=7)
    return dt


def _extract_title(text: str, date_str: str) -> str:
    title = text.replace(date_str, " ").strip()
    # Remove leading prepositions left after stripping the date fragment
    title = re.sub(r"^(в|во|на|at|on)\s+", "", title, flags=re.IGNORECASE)
    return " ".join(title.split())
