import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from bot.handlers import start, handle_message, handle_voice, list_events
from services.reminders import scheduler
from config import TELEGRAM_BOT_TOKEN


async def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("events", list_events))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    await app.initialize()
    await app.start()
    scheduler.start()
    print("Бот запущен...")
    await app.updater.start_polling()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
