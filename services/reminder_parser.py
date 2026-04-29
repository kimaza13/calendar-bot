"""
services/reminder_parser.py

Парсит команды добавления повторяющихся напоминаний.

Примеры входящих строк:
    "каждый месяц 25-го платёж CJ Logistics в 14:00"
    "напоминай за 5 дней платёж Samsung 20-го числа"
    "каждое 15-е налоговый отчёт в 10:00"
    "ежемесячно 1-го зарплата поставщику"
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

_MONTHLY_TRIGGER = re.compile(
    r"\b(каждый\s+месяц|ежемесячно|каждое|каждый|повтор)\b",
    re.IGNORECASE,
)

_DAY_PATTERN = re.compile(
    r"\b(\d{1,2})[- ]?(?:го|е|й|числа|число)?\b",
    re.IGNORECASE,
)

_TIME_PATTERN = re.compile(
    r"\b(\d{1,2}):(\d{2})\b"
)

_REMIND_DAYS_PATTERN = re.compile(
    r"\bза\s+(\d+)\s+дн",
    re.IGNORECASE,
)

# Слова которые не входят в название
_NOISE = re.compile(
    r"\b(каждый\s+месяц|ежемесячно|каждое|каждый|повтор|напоминай|напоминание"
    r"|числа|число|\d{1,2}[- ]?(?:го|е|й)?\b|за\s+\d+\s+дн\w*|в\s+\d{1,2}:\d{2})\b",
    re.IGNORECASE,
)


@dataclass
class ParsedReminder:
    title: str
    day_of_month: int      # 1-31
    remind_days: int       # за сколько дней
    hour: int              # час события
    minute: int            # минута события


def parse_reminder(text: str) -> Optional[ParsedReminder]:
    """
    Возвращает ParsedReminder если текст похож на команду напоминания,
    иначе None.
    """
    if not _MONTHLY_TRIGGER.search(text) and "напоминай" not in text.lower():
        return None

    # День месяца
    day_match = _DAY_PATTERN.search(text)
    if not day_match:
        return None
    day = int(day_match.group(1))
    if not (1 <= day <= 31):
        return None

    # Время
    time_match = _TIME_PATTERN.search(text)
    hour = int(time_match.group(1)) if time_match else 10
    minute = int(time_match.group(2)) if time_match else 0

    # За сколько дней напоминать
    remind_match = _REMIND_DAYS_PATTERN.search(text)
    remind_days = int(remind_match.group(1)) if remind_match else 3

    # Название: убираем служебные слова
    title = _MONTHLY_TRIGGER.sub("", text)
    title = _REMIND_DAYS_PATTERN.sub("", title)
    title = _TIME_PATTERN.sub("", title)
    title = _DAY_PATTERN.sub("", title)
    title = re.sub(r"\b(числа|число|напоминай|напоминание|повтор)\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" -,")

    if not title:
        title = "Платёж"

    return ParsedReminder(
        title=title,
        day_of_month=day,
        remind_days=remind_days,
        hour=hour,
        minute=minute,
    )
