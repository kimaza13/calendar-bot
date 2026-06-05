import os
import re
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import groq

# ── Конфиг ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]

groq_client = groq.Groq(api_key=GROQ_API_KEY)

# ── Состояния диалога ────────────────────────────────────────────────────────
(
    WAITING_LINK,
    WAITING_CAR_INFO,
    WAITING_KEYS,
    WAITING_CONDITION,
    WAITING_KESANSO,
    WAITING_MEDOBI,
    WAITING_MALSO,
    WAITING_CITY,
    CONFIRM,
) = range(9)

# ── Транскрипция голоса ──────────────────────────────────────────────────────
async def transcribe_voice(file_path: str) -> str:
    with open(file_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            file=("voice.ogg", f),
            model="whisper-large-v3",
            language="ru",
        )
    return result.text.strip()

# ── Парсеры ──────────────────────────────────────────────────────────────────
def parse_money(text: str) -> str:
    text = text.strip().replace(" ", "")
    nums = re.findall(r"[\d,]+", text)
    if nums:
        val = nums[0].replace(",", "")
        try:
            return f"{int(val):,}"
        except:
            pass
    return text

# ── Форматирование ───────────────────────────────────────────────────────────
def format_result(data: dict) -> str:
    lines = [
        f"{data.get('name', '—')}",
        f"{data.get('plate', '—')}",
        "",
        f"{data.get('price', '—')}",
        "",
        f"🔑 {data.get('keys', '—')}",
        "",
        f"Состояние {data.get('condition', '—')}",
        "",
        f"Кесансо {data.get('kesanso', '—')}",
        "",
        f"Медоби {parse_money(data.get('medobi', '—'))}",
        "",
        f"Мальсо {data.get('malso', '—')}",
        "",
        f"{data.get('city', '—')}",
    ]
    return "\n".join(lines)

# ── Получение текста из сообщения ────────────────────────────────────────────
async def get_text(update: Update) -> str:
    if update.message.voice:
        file = await update.message.voice.get_file()
        path = f"/tmp/voice_{update.message.message_id}.ogg"
        await file.download_to_drive(path)
        text = await transcribe_voice(path)
        os.remove(path)
        return text
    return update.message.text or ""

# ── Хэндлеры ────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Отправь ссылку на Энкар — начнём проверку.")
    return WAITING_LINK

async def receive_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "encar.com" not in text:
        await update.message.reply_text("Не вижу ссылку на Энкар. Попробуй ещё раз.")
        return WAITING_LINK

    # Сохраняем ссылку
    ctx.user_data.clear()
    ctx.user_data["url"] = text

    # Пробуем вытащить car_id для отображения
    car_id_match = re.search(r"carid=(\d+)|/cars/detail/(\d+)", text)
    if car_id_match:
        car_id = car_id_match.group(1) or car_id_match.group(2)
        ctx.user_data["car_id"] = car_id

    await update.message.reply_text(
        "Введи название и номер авто через Enter:\n\n"
        "Например:\n"
        "MINI COOPER COUNTRYMAN\n"
        "298보3562"
    )
    return WAITING_CAR_INFO

async def receive_car_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = await get_text(update)
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    if len(lines) >= 2:
        ctx.user_data["name"] = lines[0]
        ctx.user_data["plate"] = lines[1]
    elif len(lines) == 1:
        ctx.user_data["name"] = lines[0]
        ctx.user_data["plate"] = "—"
    else:
        await update.message.reply_text("Введи название и номер авто.")
        return WAITING_CAR_INFO

    await update.message.reply_text("Цена? (например: 43,400,000)")
    return WAITING_KEYS  # переиспользуем состояние для цены — см. ниже

# Переопределяем WAITING_KEYS как ввод цены
async def receive_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = await get_text(update)
    ctx.user_data["price"] = parse_money(text)
    await update.message.reply_text("Сколько ключей?")
    return WAITING_CONDITION  # переиспользуем

async def receive_keys(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = await get_text(update)
    nums = re.findall(r"\d+", text)
    ctx.user_data["keys"] = nums[0] if nums else text.strip()
    await update.message.reply_text("Состояние? (чистая / мелкие царапины / и т.д.)")
    return WAITING_KESANSO

async def receive_condition(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = await get_text(update)
    ctx.user_data["condition"] = text.strip()
    await update.message.reply_text("Кесансо? (100% / частичный / нет)")
    return WAITING_MEDOBI

async def receive_kesanso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = await get_text(update)
    ctx.user_data["kesanso"] = text.strip()
    await update.message.reply_text("Медоби? (сумма в вонах)")
    return WAITING_MALSO

async def receive_medobi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = await get_text(update)
    ctx.user_data["medobi"] = text.strip()
    await update.message.reply_text("Мальсо? (дата как 20260615, 'сразу' или 'нет')")
    return WAITING_CITY

async def receive_malso(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = await get_text(update)
    ctx.user_data["malso"] = text.strip()
    await update.message.reply_text("Город / регион?")
    return CONFIRM

async def receive_city(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = await get_text(update)
    ctx.user_data["city"] = text.strip()

    result = format_result(ctx.user_data)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Отправить", callback_data="send"),
         InlineKeyboardButton("🔄 Заново", callback_data="restart")]
    ])
    await update.message.reply_text(
        f"Вот что получилось:\n\n```\n{result}\n```",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return CONFIRM + 1  # ждём callback

async def confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "send":
        result = format_result(ctx.user_data)
        await query.message.reply_text(result)
        await query.message.reply_text("✅ Готово! Отправь новую ссылку.")
    else:
        await query.message.reply_text("Окей, начнём заново. Отправь ссылку на Энкар.")
    ctx.user_data.clear()
    return WAITING_LINK

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Отменено. Отправь ссылку чтобы начать.")
    return WAITING_LINK

# ── Запуск ───────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    CALLBACK_STATE = CONFIRM + 1

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & filters.Regex(r"encar\.com"), receive_link),
        ],
        states={
            WAITING_LINK:      [MessageHandler(filters.TEXT, receive_link)],
            WAITING_CAR_INFO:  [MessageHandler(filters.TEXT | filters.VOICE, receive_car_info)],
            WAITING_KEYS:      [MessageHandler(filters.TEXT | filters.VOICE, receive_price)],
            WAITING_CONDITION: [MessageHandler(filters.TEXT | filters.VOICE, receive_keys)],
            WAITING_KESANSO:   [MessageHandler(filters.TEXT | filters.VOICE, receive_condition)],
            WAITING_MEDOBI:    [MessageHandler(filters.TEXT | filters.VOICE, receive_kesanso)],
            WAITING_MALSO:     [MessageHandler(filters.TEXT | filters.VOICE, receive_medobi)],
            WAITING_CITY:      [MessageHandler(filters.TEXT | filters.VOICE, receive_malso)],
            CONFIRM:           [MessageHandler(filters.TEXT | filters.VOICE, receive_city)],
            CALLBACK_STATE:    [CallbackQueryHandler(confirm_callback)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
    )

    app.add_handler(conv)
    print("🚗 Car Check Bot запущен")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
