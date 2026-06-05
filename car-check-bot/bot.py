import os
import re
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import groq
import httpx

# ── Конфиг ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]

groq_client = groq.Groq(api_key=GROQ_API_KEY)

# ── Состояния ────────────────────────────────────────────────────────────────
WAITING_LINK, WAITING_CAR_INFO, WAITING_VOICE, CONFIRM = range(4)

# ── Транскрипция ─────────────────────────────────────────────────────────────
async def transcribe_voice(file_path: str) -> str:
    with open(file_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            file=("voice.ogg", f),
            model="whisper-large-v3",
            language="ru",
        )
    return result.text.strip()

# ── Claude извлекает поля из текста ─────────────────────────────────────────
async def extract_fields(text: str) -> dict:
    prompt = f"""Из текста ниже извлеки данные об автомобиле и верни ТОЛЬКО JSON без пояснений.

Текст: "{text}"

Правила:
- keys: количество ключей (только цифра: 1 или 2)
- condition: состояние кузова. Если "чистая" — пиши "чистая". Если есть повреждения — перечисли их (например: "чистая, царапина левое заднее крыло")
- kesanso: кесансо/гарантия (например: "100%" или "нет")
- medobi: медоби в вонах (только число без валюты, например: "440000"). Если не упомянуто — "нет"
- malso: мальсо (если "сразу" — пиши "сразу", если дата — формат YYYYMMDD, если нет — "нет")
- city: город или регион

Верни строго JSON:
{{"keys": "2", "condition": "чистая", "kesanso": "100%", "medobi": "440000", "malso": "сразу", "city": "Чонджу"}}"""

    response = await asyncio.to_thread(
        groq_client.chat.completions.create,
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    # Убираем markdown если есть
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)

# ── Форматирование ───────────────────────────────────────────────────────────
def format_money(text: str) -> str:
    nums = re.findall(r"[\d]+", text.replace(",", ""))
    if nums:
        try:
            return f"{int(nums[0]):,}"
        except:
            pass
    return text

def format_result(name: str, plate: str, price: str, data: dict) -> str:
    lines = [
        name,
        plate,
        "",
        price,
        "",
        f"🔑 {data.get('keys', '—')}",
        "",
        f"Состояние {data.get('condition', '—')}",
        "",
        f"Кесансо {data.get('kesanso', '—')}",
        "",
        f"Медоби {format_money(data.get('medobi', '—'))}",
        "",
        f"Мальсо {data.get('malso', '—')}",
        "",
        data.get("city", "—"),
    ]
    return "\n".join(lines)

# ── Хэндлеры ────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Отправь ссылку на Энкар.")
    return WAITING_LINK

async def receive_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "encar.com" not in text:
        await update.message.reply_text("Не вижу ссылку на Энкар. Попробуй ещё раз.")
        return WAITING_LINK

    ctx.user_data.clear()
    ctx.user_data["url"] = text
    await update.message.reply_text(
        "Введи название и номер авто (две строки):\n\nНапример:\nMINI COOPER COUNTRYMAN\n298보3562"
    )
    return WAITING_CAR_INFO

async def receive_car_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    if len(lines) < 2:
        await update.message.reply_text("Введи две строки: название и номер.")
        return WAITING_CAR_INFO

    ctx.user_data["name"] = lines[0]
    ctx.user_data["plate"] = lines[1]
    ctx.user_data["price"] = "—"

    await update.message.reply_text(
        "🎤 Теперь скажи голосовым все детали в любом порядке:\n\n"
        "Ключи, состояние, кесансо, медоби, мальсо, город\n\n"
        "Например: *«два ключа, чистая, царапина левое заднее крыло, кесансо сто процентов, медоби 440 тысяч, мальсо сразу, Чонджу»*",
        parse_mode="Markdown"
    )
    return WAITING_VOICE

async def receive_voice_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Принимаем и голос и текст
    if update.message.voice:
        file = await update.message.voice.get_file()
        path = f"/tmp/voice_{update.message.message_id}.ogg"
        await file.download_to_drive(path)
        msg = await update.message.reply_text("⏳ Распознаю...")
        text = await transcribe_voice(path)
        os.remove(path)
        await msg.edit_text(f"🗣 Распознал: _{text}_\n\n⏳ Разбираю поля...", parse_mode="Markdown")
    else:
        text = update.message.text or ""
        msg = await update.message.reply_text("⏳ Разбираю поля...")

    try:
        data = await extract_fields(text)
    except Exception as e:
        await msg.edit_text(f"❌ Не смог разобрать текст. Попробуй ещё раз.\n\nОшибка: {e}")
        return WAITING_VOICE

    ctx.user_data["fields"] = data

    name = ctx.user_data.get("name", "—")
    plate = ctx.user_data.get("plate", "—")
    price = ctx.user_data.get("price", "—")
    result = format_result(name, plate, price, data)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Отправить", callback_data="send"),
         InlineKeyboardButton("🔄 Заново", callback_data="restart"),
         InlineKeyboardButton("✏️ Цена", callback_data="edit_price")]
    ])
    await msg.edit_text(
        f"Вот что получилось:\n\n```\n{result}\n```",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return CONFIRM

async def confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "send":
        name = ctx.user_data.get("name", "—")
        plate = ctx.user_data.get("plate", "—")
        price = ctx.user_data.get("price", "—")
        data = ctx.user_data.get("fields", {})
        result = format_result(name, plate, price, data)
        await query.message.reply_text(result)
        await query.message.reply_text("✅ Готово! Отправь новую ссылку.")
        ctx.user_data.clear()
        return WAITING_LINK

    elif query.data == "restart":
        ctx.user_data.clear()
        await query.message.reply_text("Окей, начнём заново. Отправь ссылку на Энкар.")
        return WAITING_LINK

    elif query.data == "edit_price":
        await query.message.reply_text("Введи цену:")
        ctx.user_data["editing_price"] = True
        return CONFIRM

async def edit_price_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data.get("editing_price"):
        ctx.user_data["price"] = update.message.text.strip()
        ctx.user_data["editing_price"] = False

        name = ctx.user_data.get("name", "—")
        plate = ctx.user_data.get("plate", "—")
        price = ctx.user_data.get("price", "—")
        data = ctx.user_data.get("fields", {})
        result = format_result(name, plate, price, data)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Отправить", callback_data="send"),
             InlineKeyboardButton("🔄 Заново", callback_data="restart"),
             InlineKeyboardButton("✏️ Цена", callback_data="edit_price")]
        ])
        await update.message.reply_text(
            f"Вот что получилось:\n\n```\n{result}\n```",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return CONFIRM
    return CONFIRM

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Отменено. Отправь ссылку чтобы начать.")
    return WAITING_LINK

# ── Запуск ───────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & filters.Regex(r"encar\.com"), receive_link),
        ],
        states={
            WAITING_LINK:    [MessageHandler(filters.TEXT, receive_link)],
            WAITING_CAR_INFO:[MessageHandler(filters.TEXT, receive_car_info)],
            WAITING_VOICE:   [
                MessageHandler(filters.VOICE, receive_voice_details),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_voice_details),
            ],
            CONFIRM: [
                CallbackQueryHandler(confirm_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_price_handler),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
    )

    app.add_handler(conv)
    print("🚗 Car Check Bot запущен")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
