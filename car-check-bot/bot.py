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
  * "1-2 недели" / "через неделю" / "через две недели" / "일이주" / "1~2주" → "1-2 недели"
  * "через месяц" / "한달" → "через месяц"
  * Конкретная дата ("7 июля", "15 августа", "25-го") → переведи в формат YYYYMMDD с годом 2026 (например "7 июля" → "20260707")
  * Нет информации → "—" """

PLATE_PROMPT = """- plate: номерной знак авто. Корейские номера: 3 цифры + корейский слог + 4 цифры (например "298보3562", "56무2942").
  
  Whisper транскрибирует номера ДВУМЯ способами — нужно уметь читать оба:
  
  СПОСОБ 1 — Корейские числительные (самый частый):
  Цифры произносятся по-корейски: 영/공=0, 일=1, 이=2, 삼=3, 사=4, 오=5, 육=6, 칠=7, 팔=8, 구=9
  Пример: "오육 무에 이구사이" → 56 + 무 + 2942 → "56무2942"
  Пример: "이구팔 보에 삼오육이" → 298 + 보 + 3562 → "298보3562"
  
  СПОСОБ 2 — Слог транскрибируется как русская буква:
  бо/бу → 보, со/су → 소, га/ка → 가, на → 나, да/та → 다, ра/ла → 라,
  ма → 마, па/ба → 바, са/ша → 사, а → 아, жа/ча → 자, ча → 차, ха → 하
  
  Восстанови правильный номер в формате ЦИФРЫ+СЛОГ+ЦИФРЫ. Если не упомянуто — "—" """

CITY_PROMPT = """- city: город или регион. Переведи на русский язык:
  청주=Чонджу, 서울=Сеул, 부산=Пусан, 인천=Инчхон, 대구=Тэгу, 대전=Тэджон,
  광주=Кванджу, 수원=Сувон, 울산=Ульсан, 성남=Соннам, 용인=Йонъин, 전주=Чонджу,
  창원=Чханвон, 고양=Коян, 안산=Ансан, 안양=Анян, 남양주=Намянджу, 화성=Хвасон,
  평택=Пхёнтхэк, 의정부=Ыйджонбу, 시흥=Сихын, 파주=Паджу, 김포=Кимпхо,
  광명=Кванмён, 경기=Кёнги, 경남=Кённам, 경북=Кёнбук, 충남=Чхунчхам, 충북=Чхунбук,
  전남=Чоннам, 전북=Чонбук, 강원=Канвон, 제주=Чеджу, 구리=Гури, 하남=Хасон,
  오산=Осан, 군포=Кунпхо, 의왕=Ыйван, 양주=Янджу, 동두천=Тондучхон
  Если корейское название не в списке — транслитерируй на русский. Если не упомянуто — "—" """

PRICE_PROMPT = """- price: цена авто в вонах, ТОЛЬКО цифры без пробелов и запятых.
  ВАЖНО — корейский счёт: 만=10000, 천=1000, 백=100
  Примеры перевода:
  "오천오백만" = 5500 * 10000 = 55000000
  "사천삼백만" = 4300 * 10000 = 43000000
  "삼천만" = 3000 * 10000 = 30000000
  "육천만" = 6000 * 10000 = 60000000
  На русском: "пятьдесят пять миллионов" = 55000000, "сорок три миллиона" = 43000000
  Если цена озвучена как "X миллионов Y тысяч" → X*1000000 + Y*1000
  Результат записывай цифрами без пробелов. Если не упомянута — "—" """

MEDOBI_PROMPT = """- medobi: медоби/매도비 — комиссия дилера в вонах, ТОЛЬКО цифры без пробелов.
  ВАЖНО — корейский счёт: 만=10000
  Примеры: "삼십삼만" = 33 * 10000 = 330000, "사십사만" = 44 * 10000 = 440000
  На русском: "триста тридцать тысяч" = 330000, "четыреста сорок тысяч" = 440000
  Если не упомянуто — "нет" """

CONDITION_PROMPT = """- condition: состояние кузова.
  Если чистая/깨끗하다/이상없다 — "чистая".
  Если есть кузовные работы — переведи каждый пункт на русский и добавь в конце "надо смотреть":
    도색 있다 / 도색이 좀 있습니다 → "перекрас"
    판금 했다 / 판금 있습니다 → "рихтовка"
    교환했습니다 / 교체했습니다 → "замена [детали]"
    앞휀다 교환 → "замена переднего крыла"
    뒷휀다 교환 → "замена заднего крыла"
    범퍼 교환 → "замена бампера"
    도어 교환 → "замена двери"
    후드 교환 → "замена капота"
    트렁크 교환 → "замена крышки багажника"
    사고차 / 사고 있다 → "битая"
    찍힘 → "вмятина"
    긁힘 / 스크래치 → "царапина"
  Пример: "도색이 좀 있습니다, 앞휀다 교환했습니다" → "перекрас, замена переднего крыла — надо смотреть"
  Если не упомянуто — "—" """

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
    prompt = f"""Из текста извлеки данные об автомобиле и верни ТОЛЬКО JSON без каких-либо пояснений.

Текст: "{text}"

Поля:
- name: марка и модель авто (например "BMW X5", "Mercedes C-класс"). Если не упомянуто — "—"
{PLATE_PROMPT}
{PRICE_PROMPT}
- keys: количество ключей (только цифра: "1" или "2"). Если не упомянуто — "—"
{CONDITION_PROMPT}
- kesanso: кесансо (например "100%" или "нет"). Если не упомянуто — "—"
{MEDOBI_PROMPT}
{MALSO_PROMPT}
{CITY_PROMPT}

Верни строго JSON без пояснений, без markdown, без тегов think:
{{"name": "BMW X5", "plate": "56무2942", "price": "55000000", "keys": "2", "condition": "чистая", "kesanso": "100%", "medobi": "330000", "malso": "сразу", "city": "Ансан"}}"""

    response = await asyncio.to_thread(
        groq_client.chat.completions.create,
        model="qwen/qwen3.6-27b",
        messages=[
            {"role": "system", "content": "Ты помощник который извлекает данные и возвращает ТОЛЬКО валидный JSON без каких-либо пояснений, тегов think или markdown."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        max_tokens=500,
    )
    raw = response.choices[0].message.content.strip()
    # Убираем теги <think>...</think> если есть
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    # Берём только JSON часть
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        raw = match.group(0)
    return json.loads(raw)

# ── Извлечение полей из записи звонка ────────────────────────────────────────
async def extract_fields_from_call(transcript: str) -> dict:
    prompt = f"""Это транскрипция телефонного разговора с корейским автодилером. Извлеки данные и верни ТОЛЬКО JSON.

Транскрипция: "{transcript}"

Поля:
- name: марка и модель авто. Если не упомянуто — "—"
{PLATE_PROMPT}
{PRICE_PROMPT}
- keys: количество ключей ("1" или "2"). Ищи фразы типа "열쇠", "키". Если не упомянуто — "—"
{CONDITION_PROMPT}
- kesanso: кесансо/계산서. Если 100% — "100%". Если нет — "нет". Если не упомянуто — "—"
{MEDOBI_PROMPT}
{MALSO_PROMPT}
{CITY_PROMPT}

Верни строго JSON без пояснений, без markdown, без тегов think:
{{"name": "Mercedes GLE", "plate": "363소2470", "price": "96500000", "keys": "2", "condition": "перекрас, замена переднего крыла — надо смотреть", "kesanso": "100%", "medobi": "440000", "malso": "сразу", "city": "Сувон"}}"""

    response = await asyncio.to_thread(
        groq_client.chat.completions.create,
        model="qwen/qwen3.6-27b",
        messages=[
            {"role": "system", "content": "Ты помощник который извлекает данные и возвращает ТОЛЬКО валидный JSON без каких-либо пояснений, тегов think или markdown."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        max_tokens=500,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        raw = match.group(0)
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
    if not text or text == "—":
        return "—"
    if re.match(r"^\d{8}$", text):
        return f"{text[6:8]}.{text[4:6]}.{text[0:4]}"
    return text

def get_last4(plate: str) -> str:
    if not plate or plate == "—":
        return ""
    digits = re.findall(r"\d+", plate)
    if len(digits) >= 2:
        return digits[-1][-4:]
    return ""

def format_result(data: dict) -> str:
    url = data.get("url", "")
    name = data.get("name", "—")
    plate = data.get("plate", "—")
    last4 = get_last4(plate)
    name_with_plate = f"{name} {last4}".strip() if last4 else name

    lines = [
        url,
        "",
        name_with_plate,
        plate,
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
        "",
        "⚠️ Перед осмотром обязательно связаться с дилером",
    ]
    return "\n".join(lines)

# ── Хэндлеры ────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Отправь ссылку на авто.")
    return WAITING_LINK

async def receive_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "http" not in text:
        await update.message.reply_text("Не вижу ссылку. Попробуй ещё раз.")
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
        await query.message.reply_text("Отправь ссылку на авто.")
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
            MessageHandler(filters.TEXT & filters.Regex(r"http"), receive_link),
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
