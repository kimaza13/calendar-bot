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

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]
groq_client    = groq.Groq(api_key=GROQ_API_KEY)

WAITING_LINK, WAITING_VOICE, CONFIRM = range(3)

MALSO_PROMPT = """- malso: мальсо/말소. Варианты:
  * Готово прямо сейчас / "сразу" / "сейчас" → "сразу"
  * "завтра" → "завтра"
  * "послезавтра" → "послезавтра"  
  * "через несколько дней" / "через пару дней" / "через 3-5 дней" → "через несколько дней"
  * Конкретная дата ("7 июля", "15 августа", "25-го") → переведи в формат YYYYMMDD с годом 2026 (например "7 июля" → "20260707")
  * Нет информации → "—" """

PLATE_PROMPT = """- plate: номерной знак авто. Корейские номера: 3 цифры + корейский слог + 4 цифры (например "298보3562", "363소2470").
  Whisper транскрибирует слоги как русские буквы:
  бо/бу → 보, со/су → 소, га/ка → 가, на → 나, да/та → 다, ра/ла → 라, ма → 마,
  па/ба → 바, са/ша → 사, а → 아, жа/ча → 자, ча/тча → 차, ка → 카, та → 타, па → 파, ха → 하
  Восстанови правильный корейский номер. Если не упомянуто — "—" """

# ── Транскрипция ─────────────────────────────────────────────────────────────
async def transcribe_voice(file_path: str) -> str:
    with open(file_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            file=("voice.ogg", f),
            model="whisper-large-v3",
            language="ru",
        )
    return result.text.strip()

# ── Извлечение полей через LLM (голосовое от тебя) ───────────────────────────
async def extract_fields(text: str) -> dict:
    prompt = f"""Из текста извлеки данные об автомобиле и верни ТОЛЬКО JSON.

Текст: "{text}"

Поля:
- name: марка и модель авто (например "MINI COOPER COUNTRYMAN", "Mercedes GLE"). Если не упомянуто — "—"
{PLATE_PROMPT}
- price: цена только цифры без пробелов (например "43400000"). Если не упомянута — "—"
- keys: количество ключей (только цифра: "1" или "2"). Если не упомянуто — "—"
- condition: состояние. Если чистая — "чистая". Если есть повреждения — перечисли (например "царапина левое заднее крыло"). Если не упомянуто — "—"
- kesanso: кесансо (например "100%" или "нет"). Если не упомянуто — "—"
- medobi: медоби только цифры (например "440000"). Если нет или не упомянуто — "нет"
{MALSO_PROMPT}
- city: город или регион (например "Чонджу", "Сеул", "Пусан"). Если не упомянуто — "—"

Верни строго JSON без пояснений:
{{"name": "MINI COOPER COUNTRYMAN", "plate": "298보3562", "price": "43400000", "keys": "2", "condition": "чистая", "kesanso": "100%", "medobi": "440000", "malso": "сразу", "city": "Чонджу"}}"""

    response = await asyncio.to_thread(
        groq_client.chat.completions.create,
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)

# ── Извлечение полей из записи звонка ────────────────────────────────────────
async def extract_fields_from_call(transcript: str) -> dict:
    prompt = f"""Это транскрипция телефонного разговора с корейским автодилером. Извлеки данные и верни ТОЛЬКО JSON.

Транскрипция: "{transcript}"

Поля:
- name: марка и модель авто. Если не упомянуто — "—"
{PLATE_PROMPT}
- price: цена в вонах только цифры. Если не упомянута — "—"
- keys: количество ключей (цифра "1" или "2"). Ищи фразы типа "열쇠", "키", "ключ". Если не упомянуто — "—"
- condition: состояние кузова. Если чистая/깨끗 — "чистая". Если есть повреждения — перечисли на русском. Если не упомянуто — "—"
- kesanso: кесансо/계산서. Если 100% — "100%". Если нет — "нет". Если не упомянуто — "—"
- medobi: медоби/매도비 в вонах только цифры. Если нет — "нет"
{MALSO_PROMPT}
- city: город или регион дилера. Если не упомянуто — "—"

Верни строго JSON:
{{"name": "Mercedes GLE", "plate": "363소2470", "price": "96500000", "keys": "2", "condition": "чистая", "kesanso": "100%", "medobi": "440000", "malso": "сразу", "city": "Сувон"}}"""

    response = await asyncio.to_thread(
        groq_client.chat.completions.create,
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)

# ── Форматирование ───────────────────────────────────────────────────────────
def fmt_money(text: str) -> str:
    if not text or text in ("—", "нет"):
        return text
    nums = re.findall(r"\d+", text.replace(",", "").replace(" ", ""))
    if nums:
        try:
            return f"{int(''.join(nums)):,}"
        except:
            pass
    return text

def fmt_malso(text: str) -> str:
    """Форматирует мальсо: дату YYYYMMDD → читаемый вид."""
    if not text or text == "—":
        return "—"
    if re.match(r"^\d{8}$", text):
        # 20260707 → 07.07.2026
        return f"{text[6:8]}.{text[4:6]}.{text[0:4]}"
    return text

def format_result(data: dict) -> str:
    url = data.get("url", "")
    lines = [
        url,
        "",
        data.get("name", "—"),
        data.get("plate", "—"),
        "",
        fmt_money(data.get("price", "—")),
        "",
        f"🔑 {data.get('keys', '—')}",
        "",
        f"Состояние: {data.get('condition', '—')}",
        "",
        f"Кесансо: {data.get('kesanso', '—')}",
        "",
        f"Медоби: {fmt_money(data.get('medobi', '—'))}",
        "",
        f"Мальсо: {fmt_malso(data.get('malso', '—'))}",
        "",
        f"📍 {data.get('city', '—')}",
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
        "🎤 Отправь голосовое или запись звонка (m4a/mp3):\n\n"
        "Марка, номер, цена, ключи, состояние, кесансо, медоби, мальсо, город"
    )
    return WAITING_VOICE

async def receive_audio_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    audio = update.message.audio or update.message.document
    file = await audio.get_file()
    ext = "m4a" if (update.message.audio or (update.message.document and "m4a" in (update.message.document.file_name or ""))) else "mp3"
    path = f"/tmp/audio_{update.message.message_id}.{ext}"
    await file.download_to_drive(path)
    msg = await update.message.reply_text("⏳ Транскрибирую звонок...")

    try:
        with open(path, "rb") as f:
            result = groq_client.audio.transcriptions.create(
                file=(f"audio.{ext}", f),
                model="whisper-large-v3",
                language="ko",
            )
        transcript = result.text.strip()
        os.remove(path)
    except Exception as e:
        await msg.edit_text(f"❌ Не смог транскрибировать файл.\n\n{e}")
        return WAITING_VOICE

    await msg.edit_text("🗣 Транскрипция готова.\n⏳ Разбираю данные...")

    try:
        data = await extract_fields_from_call(transcript)
    except Exception as e:
        await msg.edit_text(f"❌ Не смог разобрать. Попробуй ещё раз.\n\n{e}")
        return WAITING_VOICE

    data["url"] = ctx.user_data.get("url", "")
    ctx.user_data["fields"] = data
    result_text = format_result(data)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Отправить", callback_data="send"),
        InlineKeyboardButton("🔄 Заново", callback_data="restart"),
    ]])
    await msg.edit_text(
        f"```\n{result_text}\n```",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return CONFIRM

async def receive_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.voice:
        file = await update.message.voice.get_file()
        path = f"/tmp/voice_{update.message.message_id}.ogg"
        await file.download_to_drive(path)
        msg = await update.message.reply_text("⏳ Распознаю...")
        text = await transcribe_voice(path)
        os.remove(path)
        await msg.edit_text(f"🗣 _{text}_\n\n⏳ Разбираю...", parse_mode="Markdown")
    else:
        text = update.message.text or ""
        msg = await update.message.reply_text("⏳ Разбираю...")

    try:
        data = await extract_fields(text)
    except Exception as e:
        await msg.edit_text(f"❌ Не смог разобрать. Попробуй ещё раз.\n\n{e}")
        return WAITING_VOICE

    data["url"] = ctx.user_data.get("url", "")
    ctx.user_data["fields"] = data
    result = format_result(data)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Отправить", callback_data="send"),
        InlineKeyboardButton("🔄 Заново", callback_data="restart"),
    ]])
    await msg.edit_text(
        f"```\n{result}\n```",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return CONFIRM

async def confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "send":
        result = format_result(ctx.user_data.get("fields", {}))
        await query.message.reply_text(result)
        ctx.user_data.clear()
        await query.message.reply_text("✅ Готово! Отправь новую ссылку.")
        return WAITING_LINK

    elif query.data == "restart":
        ctx.user_data.clear()
        await query.message.reply_text("Отправь ссылку на Энкар.")
        return WAITING_LINK

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
            WAITING_LINK:  [MessageHandler(filters.TEXT, receive_link)],
            WAITING_VOICE: [
                MessageHandler(filters.VOICE, receive_voice),
                MessageHandler(filters.AUDIO, receive_audio_file),
                MessageHandler(filters.Document.MimeType("audio/mp4") | filters.Document.MimeType("audio/mpeg") | filters.Document.MimeType("audio/m4a"), receive_audio_file),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_voice),
            ],
            CONFIRM: [CallbackQueryHandler(confirm_callback)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
    )

    app.add_handler(conv)
    print("🚗 Car Check Bot запущен")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
