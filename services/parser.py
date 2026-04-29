from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import Optional
from zoneinfo import ZoneInfo
import re
import dateparser

_TZ = ZoneInfo("Asia/Seoul")


@dataclass
class ParsedEvent:
    title: str
    start: datetime
    end: datetime


# "7 вечера" / "8 часов вечера" → "20:00"
_TIME_OF_DAY = {
    "ночи":   (0,  6),
    "утра":   (0,  11),
    "дня":    (12, 17),
    "вечера": (12, 23),
}

_TOD_PATTERN = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s+(?:час(?:ов|а)?\s+)?(ночи|утра|дня|вечера)\b",
    re.IGNORECASE,
)

# "1 мая" → "1 May 2026"
_MONTHS_RU = {
    "января": (1, "January"), "февраля": (2, "February"), "марта": (3, "March"),
    "апреля": (4, "April"), "мая": (5, "May"), "июня": (6, "June"),
    "июля": (7, "July"), "августа": (8, "August"), "сентября": (9, "September"),
    "октября": (10, "October"), "ноября": (11, "November"), "декабря": (12, "December"),
}
_MONTH_PATTERN = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(_MONTHS_RU) + r")\b",
    re.IGNORECASE,
)

_MONTHS_EN = (
    r"(?:January|February|March|April|May|June|July"
    r"|August|September|October|November|December)"
)
_WEEKDAYS_RU = r"(?:понедельник[ауе]?|вторник[ауе]?|среду?|четверг[ауе]?|пятниц[ауе]?|субботу?[ыа]?|воскресень[ею]?)"
_WEEKDAYS_EN = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"

# Tokens that represent date/time (after normalization).
# We pass only these to dateparser, keeping the event title separate.
_DT_TOKENS = re.compile(
    r"\b\d{1,2}\s+" + _MONTHS_EN + r"\s+\d{4}\b"           # "1 May 2026"
    r"|\b\d{1,2}:\d{2}\b"                                    # "20:00"
    r"|\bчерез\s+\d+\s+\w+"                                  # "через 2 часа"
    r"|\bпослезавтра\b|\bзавтра\b|\bсегодня\b"               # relative RU
    r"|\bday after tomorrow\b|\btomorrow\b|\btoday\b"         # relative EN
    r"|\bследующ\w+\s+(?:" + _WEEKDAYS_EN + r"|" + _WEEKDAYS_RU + r")"
    r"|\b" + _WEEKDAYS_EN + r"\b"
    r"|\b" + _WEEKDAYS_RU + r"\b",
    re.IGNORECASE | re.UNICODE,
)

_DATEPARSER_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "RETURN_AS_TIMEZONE_AWARE": True,
    "TIMEZONE": "Asia/Seoul",
    "TO_TIMEZONE": "Asia/Seoul",
    "PREFER_DAY_OF_MONTH": "first",
}


def _normalize_time_of_day(text: str) -> str:
    def replace(m: re.Match) -> str:
        hour = int(m.group(1))
        minutes = m.group(2) or "00"
        period = m.group(3).lower()
        low, _ = _TIME_OF_DAY[period]
        if hour < 12 and low >= 12:
            hour += 12
        elif hour == 12 and low == 0:
            hour = 0
        return f"{hour:02d}:{minutes}"
    return _TOD_PATTERN.sub(replace, text)


def _normalize_month_names(text: str) -> str:
    def replace(m: re.Match) -> str:
        day = int(m.group(1))
        month_num, month_en = _MONTHS_RU[m.group(2).lower()]
        today = date.today()
        year = today.year if (month_num, day) >= (today.month, today.day) else today.year + 1
        return f"{day} {month_en} {year}"
    return _MONTH_PATTERN.sub(replace, text)


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
    normalized = _normalize_month_names(normalized)
    normalized = re.sub(r"\s+в\s+", " ", normalized)

    # Extract date/time tokens; pass only them to dateparser (no Russian title text).
    tokens = _DT_TOKENS.findall(normalized)
    dt_str = " ".join(t.strip() for t in tokens)
    if not dt_str:
        return None

    # Title is everything that is NOT a date/time token.
    title = _DT_TOKENS.sub(" ", normalized).strip()
    title = re.sub(r"^(в|во|на|at|on)\s+", "", title, flags=re.IGNORECASE)
    title = " ".join(title.split()) or "Событие"

    print(f"PARSER: dt_str='{dt_str}' title='{title}'", flush=True)

    dt = dateparser.parse(dt_str, languages=["ru", "en"], settings=_DATEPARSER_SETTINGS)
    if not dt:
        return None

    dt = _ensure_future(dt)
    print(f"PARSER OUT: dt={dt} title='{title}'", flush=True)
    return ParsedEvent(title=title, start=dt, end=dt + timedelta(hours=1))


def _ensure_future(dt: datetime) -> datetime:
    now = datetime.now(tz=dt.tzinfo)
    while dt.date() < now.date():
        dt += timedelta(days=7)
    return dt
