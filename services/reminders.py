from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
from config import REMINDER_MINUTES

scheduler = AsyncIOScheduler()


def schedule_reminder(bot, chat_id: int, title: str, event_time: datetime):
    remind_at = event_time - timedelta(minutes=REMINDER_MINUTES)
    if remind_at <= datetime.now(remind_at.tzinfo):
        return
    scheduler.add_job(
        _send_reminder,
        trigger="date",
        run_date=remind_at,
        args=[bot, chat_id, title, event_time],
        id=f"reminder_{chat_id}_{title}_{event_time.isoformat()}",
        replace_existing=True,
    )


async def _send_reminder(bot, chat_id: int, title: str, event_time: datetime):
    await bot.send_message(
        chat_id=chat_id,
        text=f"Напоминание: «{title}» начнётся через {REMINDER_MINUTES} минут ({event_time.strftime('%H:%M')})",
    )
