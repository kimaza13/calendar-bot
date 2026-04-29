"""
services/scheduler.py

Запускает фоновый поток, который каждую минуту проверяет
таблицу reminders и отправляет сообщения в Telegram.

Использование в main.py:
    from services.scheduler import start_scheduler
    start_scheduler()
"""
from __future__ import annotations
import threading
import time
import logging
from datetime import date

from services.reminders import get_due_reminders, mark_sent
from bot import api as tg

log = logging.getLogger(__name__)

_INTERVAL_SECONDS = 60  # проверка каждую минуту


def _check_and_send() -> None:
    try:
        due = get_due_reminders()
        for row, event_date in due:
            days_left = (event_date - date.today()).days
            text = (
                f"⏰ Напоминание: через {days_left} дн. — «{row['title']}»\n"
                f"📅 Дата события: {event_date.strftime('%d.%m.%Y')} "
                f"в {row['hour']:02d}:{row['minute']:02d}"
            )
            tg.send_message(row["chat_id"], text)
            mark_sent(row["id"])
            log.info(f"Sent reminder id={row['id']} to chat={row['chat_id']}")
    except Exception as e:
        log.error(f"Scheduler error: {e}")


def _loop() -> None:
    while True:
        _check_and_send()
        time.sleep(_INTERVAL_SECONDS)


def start_scheduler() -> None:
    t = threading.Thread(target=_loop, daemon=True, name="reminder-scheduler")
    t.start()
    log.info("Reminder scheduler started.")
