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

# ── Транскрипция ─────────────────────────────────────────────────────────────
async def transcribe_voice(file_path: str) -> str:
    with open(file_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            file=("voice.ogg", f),
            model="whisper-large-v3",
            language="ru",
        )
    return result.text.strip()

# ── Извлечение полей через LLM ───────────────────────────────────────────────
async def extract_fields(text: str) -> dict:
    prompt = f"""Из текста извлеки данные об автомобиле и верни ТОЛЬКО JSON.

Текст: "{text}"

Поля:
- name: название авто (марка и модель, например "MINI COOPER COUNTRYMAN" или "MB C CLASS"). Если не упомянуто — "—"
- plate: номерной знак авто. Корейские номера состоят из 3 цифр + корейский слог + 4 цифры (например "298보3562", "363소2470", "155가1234"). Whisper транскрибирует корейские слоги как русские буквы или слова:
  * "бо/бу/во" → 보
  * "со/су/со" → 소  
  * "га/ка/гга" → 가
  * "나/на/на" → 나
  * "다/да/та" → 다
  * "라/ра/ла" → 라
  * "마/ма" → 마
  * "바/па/ба" → 바
  * "사/са/ша" → 사
  * "아/а" → 아
  * "자/жа/ча" → 자
  * "차/ча/тча" → 차
  * "카/ка" → 카
  * "타/та" → 타
  * "파/па" → 파
  * "하/ха" → 하
  Восстанови правильный корейский номер из транскрипции. Если не упомянуто — "—"
- price: цена только цифры без пробелов (например "43400000"). Если не упомянута — "—"
- keys: количество ключей (только цифра: "1" или "2")
- condition: состояние. Если чистая — "чистая". Если есть повреждения — перечисли (например "чистая, царапина левое заднее крыло")
- kesanso: кесансо (например "100%" или "нет")
- medobi: медоби только цифры (например "440000"). Если нет — "нет"
- malso: мальсо. Если "сразу" — пиши "сразу". Если дата (например "7 июля", "15 августа") — переведи в формат YYYYMMDD используя 2026 год (например "7 июля" → "20260707"). Если нет — "нет"
- city: город или регион

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

# ── Форматирование ───────────────────────────────────────────────────────────
def fmt_money(text: str) -> str:
    if not text or text == "—" or text == "нет":
        return text
    nums = re.findall(r"\d+", text.replace(",", "").replace(" ", ""))
    if nums:
        try:
            return f"{int(''.join(nums)):,}"
        except:
            pass
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
        f"Состояние {data.get('condition', '—')}",
        "",
        f"Кесансо {data.get('kesanso', '—')}",
        "",
        f"Медоби {fmt_money(data.get('medobi', '—'))}",
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
        "🎤 Скажи голосовым все детали в любом порядке:\n\n"
        "Название, номер, цена, ключи, состояние, кесансо, медоби, мальсо, город\n\n"
        "Например: _«Мини Купер Кантримэн, 298보3562, 43 миллиона 400 тысяч, два ключа, чистая, кесансо 100%, медоби 440 тысяч, мальсо сразу, Чонджу»_",
        parse_mode="Markdown"
    )
    return WAITING_VOICE

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

    ctx.user_data["fields"] = data
    data["url"] = ctx.user_data.get("url", "")
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
