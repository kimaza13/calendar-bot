import os
import re
import json
import asyncio
import httpx
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import groq

# ── Конфиг ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]
ALLOWED_USERS  = set(os.environ.get("ALLOWED_USER_IDS", "").split(","))

groq_client = groq.Groq(api_key=GROQ_API_KEY)

# ── Состояния диалога ────────────────────────────────────────────────────────
(
    WAITING_LINK,
    WAITING_KEYS,
    WAITING_CONDITION,
    WAITING_KESANSO,
    WAITING_MEDOBI,
    WAITING_MALSO,
    WAITING_CITY,
    CONFIRM,
) = range(8)

# ── Парсинг Энкар ────────────────────────────────────────────────────────────
async def fetch_encar_info(url: str) -> dict:
    """Вытаскивает car_id из URL и запрашивает API Энкар."""
    car_id_match = re.search(r"carid=(\d+)", url)
    if not car_id_match:
        car_id_match = re.search(r"/cars/detail/(\d+)", url)
    if not car_id_match:
        return {}
    car_id = car_id_match.group(1)
    api_url = f"https://api.encar.com/search/car/list/premium?count=1&q=(Id:{car_id})"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(api_url, headers={"User-Agent": "Mozilla/5.0"})
            data = resp.json()
            items = data.get("SearchResults", [])
            if items:
                item = items[0]
                name = f"{item.get('Manufacturer','')} {item.get('Model','')} {item.get('Badge','')}{item.get('BadgeDetail','')}".strip()
                price = item.get("Price", 0)
                plate = item.get("PlateNo", "")
                return {"name": name, "price": price * 10000, "plate": plate}
    except Exception:
        pass
    return {}

# ── Транскрипция голоса ──────────────────────────────────────────────────────
async def transcribe_voice(file_path: str) -> str:
    with open(file_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            file=("voice.ogg", f),
            model="whisper-large-v3",
            language="ru",
        )
    return result.text.strip()

# ── Нормализация ответов ─────────────────────────────────────────────────────
def normalize(text: str) -> str:
    return text.strip()

def parse_keys(text: str) -> str:
    nums = re.findall(r"\d+", text)
    return nums[0] if nums else text.strip()

def parse_money(text: str) -> str:
    """Приводит к виду 'XXX,000' если введено число."""
    text = text.strip().replace(" ", "")
    nums = re.findall(r"[\d,]+", text)
    if nums:
        val = nums[0].replace(",", "")
        try:
            n = int(val)
            return f"{n:,}"
        except:
            pass
    return text

# ── Форматирование итогового сообщения ──────────────────────────────────────
def format_result(data: dict) -> str:
    keys_emoji = "🔑" * int(data.get("keys", 1))
    malso_val = data.get("malso", "—")
    if malso_val.lower() not in ("нет", "—", "no", "없음"):
        malso_val = f"с {malso_val}"

    lines = [
        f"{data.get('name', '—')}",
        f"{data.get('plate', '—')}",
        "",
        f"{int(data.get('price',0)):,}" if data.get('price') else "—",
        "",
        f"{keys_emoji} {data.get('keys','—')}",
        "",
        f"Состояние {data.get('condition','—')}",
        "",
        f"Кесансо {data.get('kesanso','—')}",
        "",
        f"Медоби {parse_money(data.get('medobi','—'))}",
        "",
        f"Мальсо {malso_val}",
        "",
        f"{data.get('city','—')}",
    ]
    return "\n".join(lines)

# ── Хэндлеры ────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Отправь мне ссылку на Энкар — начнём проверку авто.",
    )
    return WAITING_LINK

async def receive_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    url_match = re.search(r"https?://\S+encar\S+", text)
    if not url_match:
        await update.message.reply_text("Не вижу ссылку на Энкар. Попробуй ещё раз.")
        return WAITING_LINK

    url = url_match.group(0)
    ctx.user_data["url"] = url
    msg = await update.message.reply_text("⏳ Получаю данные с Энкар...")
    info = await fetch_encar_info(url)
    ctx.user_data["name"]  = info.get("name", "")
    ctx.user_data["price"] = info.get("price", 0)
    ctx.user_data["plate"] = info.get("plate", "")

    summary = f"🚗 *{ctx.user_data['name'] or 'Авто'}*"
    if ctx.user_data["price"]:
        summary += f"\n💰 {int(ctx.user_data['price']):,} ₩"
    if ctx.user_data["plate"]:
        summary += f"\n🔢 {ctx.user_data['plate']}"

    await msg.edit_text(summary + "\n\nСколько ключей? (напиши цифру или голосом)", parse_mode="Markdown")
    return WAITING_KEYS

async def receive_voice_or_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE, state: int):
    """Универсальный обработчик — голос или текст."""
    if update.message.voice:
        file = await update.message.voice.get_file()
        path = f"/tmp/voice_{update.message.message_id}.ogg"
        await file.download_to_drive(path)
        text = await transcribe_voice(path)
        os.remove(path)
    else:
        text = update.message.text or ""
    return text

QUESTIONS = {
    WAITING_KEYS:      ("keys",      "parse_keys",  "Состояние авто? (чистая / мелкие царапины / и т.д.)"),
    WAITING_CONDITION: ("condition", "normalize",   "Кесансо? (100% / частичный / нет)"),
    WAITING_KESANSO:   ("kesanso",   "normalize",   "Медоби? (сумма в вонах)"),
    WAITING_MEDOBI:    ("medobi",    "parse_money", "Мальсо готово? (дата или 'нет')"),
    WAITING_MALSO:     ("malso",     "normalize",   "Город / регион?"),
    WAITING_CITY:      ("city",      "normalize",   None),
}

PARSERS = {
    "parse_keys":  parse_keys,
    "parse_money": parse_money,
    "normalize":   normalize,
}

async def handle_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state = ctx.user_data.get("state", WAITING_KEYS)
    text = await receive_voice_or_text(update, ctx, state)

    field, parser_name, next_question = QUESTIONS[state]
    parser = PARSERS[parser_name]
    ctx.user_data[field] = parser(text)

    next_state = state + 1

    if next_state == CONFIRM:
        # Показываем итог
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
        ctx.user_data["state"] = CONFIRM
        return CONFIRM
    else:
        ctx.user_data["state"] = next_state
        await update.message.reply_text(next_question)
        return next_state

async def confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "send":
        result = format_result(ctx.user_data)
        await query.message.reply_text(result)
        await query.message.reply_text("✅ Готово! Отправь новую ссылку для следующей машины.")
        ctx.user_data.clear()
        return WAITING_LINK
    else:
        ctx.user_data.clear()
        await query.message.reply_text("Окей, начнём заново. Отправь ссылку на Энкар.")
        return WAITING_LINK

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Отменено. Отправь ссылку чтобы начать заново.")
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
            WAITING_LINK:      [MessageHandler(filters.TEXT, receive_link)],
            WAITING_KEYS:      [MessageHandler(filters.TEXT | filters.VOICE, handle_step)],
            WAITING_CONDITION: [MessageHandler(filters.TEXT | filters.VOICE, handle_step)],
            WAITING_KESANSO:   [MessageHandler(filters.TEXT | filters.VOICE, handle_step)],
            WAITING_MEDOBI:    [MessageHandler(filters.TEXT | filters.VOICE, handle_step)],
            WAITING_MALSO:     [MessageHandler(filters.TEXT | filters.VOICE, handle_step)],
            WAITING_CITY:      [MessageHandler(filters.TEXT | filters.VOICE, handle_step)],
            CONFIRM:           [CallbackQueryHandler(confirm_callback)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
    )

    app.add_handler(conv)
    print("🚗 Car Check Bot запущен")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
