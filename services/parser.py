from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import re
import dateparser.search

_TZ = ZoneInfo("Asia/Tashkent")


@dataclass
class ParsedEvent:
    title: str
    start: datetime
    end: datetime


# "7 вечера" / "8 часов вечера" → "19:00"
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

# "1 мая" / "15 июня" → "01.05" / "15.06"
_MONTHS_RU = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_MONTH_PATTERN = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(_MONTHS_RU) + r")\b",
    re.IGNORECASE,
)


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
        month = _MONTHS_RU[m.group(2).lower()]
        return f"{day:02d}.{month:02d}"
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
    results = dateparser.search.search_dates(
        normalized,
        languages=["ru", "en"],
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": "Asia/Tashkent",
        },
    )
    if not results:
        return None

    _, dt = _pick_best(results)
    dt = _ensure_future(dt)
    title = _extract_title(normalized, *[s for s, _ in results]) or "Событие"
    result = ParsedEvent(title=title, start=dt, end=dt + timedelta(hours=1))
    print(f"PARSER DEBUG: normalized='{normalized}' raw_results={[(s, str(d)) for s, d in results]} dt={dt} tzinfo={dt.tzinfo}")
    return result


def _pick_best(results: list) -> tuple:
    # dateparser sometimes splits "1 мая в 20:00" into two results:
    # ("1 мая", May-1 00:00) and ("20:00", today 20:00).
    # Combine: take the date from the midnight result, time from the timed result.
    if len(results) == 1:
        return results[0]
    timed = [(s, d) for s, d in results if d.hour != 0 or d.minute != 0]
    dated = [(s, d) for s, d in results if d.hour == 0 and d.minute == 0]
    if timed and dated:
        _, base = dated[0]
        _, time_dt = timed[0]
        return (dated[0][0], base.replace(hour=time_dt.hour, minute=time_dt.minute))
    return timed[0] if timed else results[0]


def _ensure_future(dt: datetime) -> datetime:
    now = datetime.now(tz=dt.tzinfo)
    # Compare by date only: if the date itself is in the past, advance by weeks.
    # Avoids bumping "сегодня" (midnight) into next week just because time passed.
    while dt.date() < now.date():
        dt += timedelta(days=7)
    return dt


def _extract_title(text: str, *date_strs: str) -> str:
    for s in date_strs:
        text = text.replace(s, " ")
    text = text.strip()
    text = re.sub(r"^(в|во|на|at|on)\s+", "", text, flags=re.IGNORECASE)
    return " ".join(text.split())
