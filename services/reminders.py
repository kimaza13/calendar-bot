"""
services/reminders.py

Хранение повторяющихся платежей и напоминаний в SQLite.
Таблица reminders:
    id          INTEGER PRIMARY KEY
    chat_id     INTEGER   — кому слать
    title       TEXT      — название события
    day_of_month INTEGER  — день месяца (1-31), NULL если не ежемесячное
    remind_days INTEGER   — за сколько дней напоминать (default 3)
    hour        INTEGER   — час события (default 10)
    minute      INTEGER   — минута события (default 0)
    last_sent   TEXT      — дата последней отправки YYYY-MM-DD (чтобы не дублировать)
    created_at  TEXT
"""
from __future__ import annotations
import sqlite3
import os
from datetime import date, timedelta
from typing import Optional

_DB_PATH = os.getenv("REMINDERS_DB", "reminders.db")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id       INTEGER NOT NULL,
                title         TEXT    NOT NULL,
                day_of_month  INTEGER,
                remind_days   INTEGER NOT NULL DEFAULT 3,
                hour          INTEGER NOT NULL DEFAULT 10,
                minute        INTEGER NOT NULL DEFAULT 0,
                last_sent     TEXT,
                created_at    TEXT    DEFAULT (date('now'))
            )
        """)


def add_reminder(
    chat_id: int,
    title: str,
    day_of_month: int,
    remind_days: int = 3,
    hour: int = 10,
    minute: int = 0,
) -> int:
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO reminders
               (chat_id, title, day_of_month, remind_days, hour, minute)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (chat_id, title, day_of_month, remind_days, hour, minute),
        )
        return cur.lastrowid


def list_reminders(chat_id: int) -> list[sqlite3.Row]:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM reminders WHERE chat_id = ? ORDER BY day_of_month",
            (chat_id,),
        ).fetchall()


def delete_reminder(reminder_id: int, chat_id: int) -> bool:
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM reminders WHERE id = ? AND chat_id = ?",
            (reminder_id, chat_id),
        )
        return cur.rowcount > 0


def get_due_reminders(today: Optional[date] = None) -> list[sqlite3.Row]:
    """
    Возвращает напоминания, которые нужно отправить сегодня.
    Напоминание отправляется когда:
        день_события - remind_days == today
    и ещё не отправлялось сегодня (last_sent != today).
    """
    if today is None:
        today = date.today()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM reminders WHERE day_of_month IS NOT NULL"
        ).fetchall()

    due = []
    for row in rows:
        target_day = row["day_of_month"]
        remind_days = row["remind_days"]

        # Находим ближайшую дату с нужным числом месяца
        event_date = _next_occurrence(today, target_day)
        remind_date = event_date - timedelta(days=remind_days)

        if remind_date == today:
            last_sent = row["last_sent"]
            if last_sent != str(today):
                due.append((row, event_date))
    return due


def mark_sent(reminder_id: int, today: Optional[date] = None) -> None:
    if today is None:
        today = date.today()
    with _conn() as con:
        con.execute(
            "UPDATE reminders SET last_sent = ? WHERE id = ?",
            (str(today), reminder_id),
        )


def _next_occurrence(from_date: date, day: int) -> date:
    """Ближайшая дата с нужным числом месяца (включая текущий месяц)."""
    import calendar
    year, month = from_date.year, from_date.month
    for _ in range(13):  # максимум 13 месяцев вперёд
        last_day = calendar.monthrange(year, month)[1]
        actual_day = min(day, last_day)
        candidate = date(year, month, actual_day)
        if candidate >= from_date:
            return candidate
        month += 1
        if month > 12:
            month = 1
            year += 1
    return date(year, month, day)
