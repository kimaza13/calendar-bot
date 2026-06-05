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

# ── Состояния ────────────────────────────────────────────────────────────────
WAITING_INPUT, CONFIRM = range(2)

# ── Транскрипция ─────────────────────────────────────────────────────────────
async def transcribe_voice(file_path: str) -> str:
    with open(file_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            file=("voice.ogg", f),
            model="whisper-large-v3",
            language="ru",
        )
    return result.text.strip()

# ── Извлечение параметров через LLM ─────────────────────────────────────────
async def extract_params(text: str) -> dict:
    prompt = f"""Из текста извлеки параметры автомобиля и верни ТОЛЬКО JSON.

Текст: "{text}"

Поля:
- price_krw: цена авто в вонах только цифры (например "39900000"). Если не упомянута — null
- engine_cc: объём двигателя в см³ только цифры (например "1500"). Если не упомянут — null
- engine_hp: мощность в лошадиных силах только цифры (например "136"). Если не упомянута — null
- age: возраст авто — одно из: "new" (до 3 лет), "old" (3-5 лет), "older" (старше 5 лет). Если не упомянут — null
- purpose: "personal" (физлицо для себя) или "commercial" (юрлицо/перепродажа). По умолчанию "personal"

Примеры фраз:
- "38 миллионов вон" → price_krw: "38000000"
- "полтора литра" или "1500 кубиков" → engine_cc: "1500"
- "136 лошадей" → engine_hp: "136"
- "три года" или "новая" → age: "new"
- "пять лет" или "старая" → age: "old"

Верни строго JSON:
{{"price_krw": "39900000", "engine_cc": "1500", "engine_hp": "136", "age": "old", "purpose": "personal"}}"""

    response = await asyncio.to_thread(
        groq_client.chat.completions.create,
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)

# ── Расчёт ───────────────────────────────────────────────────────────────────
KOREA_EXPENSES = 2_000_000  # KRW
KRW_TO_RUB = 0.05347
KRW_TO_USD = 1 / 1400
BROKER_FEES = 110_000
SERVICE_FEE = 100_000
CUSTOMS_DOC_FEE = 18_465
AUTOVOZ_MSK = 210_000

def get_customs_duty(price_rub, cc, age):
    if age == "new":
        brackets = [
            (8500*90,   0.54, 2.5),
            (16700*90,  0.48, 3.5),
            (42300*90,  0.48, 5.5),
            (84500*90,  0.48, 7.5),
            (float('inf'), 0.48, 15),
        ]
        for limit, pct, eur_cc in brackets:
            if price_rub <= limit:
                return max(price_rub * pct, cc * eur_cc * 90)
    else:
        if age == "old":
            cc_rates = [(1000,1.5),(1500,1.7),(1800,2.5),(2300,2.7),(3000,3.0),(float('inf'),3.6)]
        else:
            cc_rates = [(1000,3.0),(1500,3.2),(1800,3.5),(2300,4.8),(3000,5.0),(float('inf'),5.7)]
        for limit, rate in cc_rates:
            if cc <= limit:
                return cc * rate * 90
    return 0

def get_utilsbor(cc, hp, age, purpose):
    is_old = age in ("old", "older")
    if purpose == "personal" and hp <= 160:
        return 20000 * (0.26 if is_old else 0.17)
    if cc <= 2000:
        table = [(160,0.17,0.26),(190,45,74.64),(220,47.64,79.2),(250,50.52,83.88),
                 (280,57.12,91.92),(310,64.56,100.56),(float('inf'),72.96,110.16)]
    elif cc <= 3000:
        table = [(160,0.17,0.26),(190,112.52,170.36),(220,115.34,172.8),(250,118.2,175.08),
                 (280,120.12,177.6),(310,126,183),(float('inf'),131.04,188.52)]
    else:
        return 20000 * (250 if is_old else 180)
    for hp_limit, k_new, k_old in table:
        if hp <= hp_limit:
            return 20000 * (k_old if is_old else k_new)
    return 20000 * (110.16 if is_old else 72.96)

def get_customs_doc_fee(price_rub):
    brackets = [
        (200_000, 1_231), (450_000, 2_462), (1_200_000, 4_924),
        (2_700_000, 13_541), (4_200_000, 18_465), (5_500_000, 21_344),
        (10_000_000, 49_240), (float('inf'), 73_860),
    ]
    for limit, fee in brackets:
        if price_rub <= limit:
            return fee
    return 73_860

def fmt(n):
    return f"₽{round(n):,}".replace(",", " ")

def calculate(params: dict, krw_rub: float = None) -> dict:
    price_krw = int(params.get("price_krw") or 39_900_000)
    cc = int(params.get("engine_cc") or 1500)
    hp = int(params.get("engine_hp") or 136)
    age = params.get("age") or "old"
    purpose = params.get("purpose") or "personal"
    rate = krw_rub or KRW_TO_RUB

    total_krw = price_krw + KOREA_EXPENSES
    price_rub = total_krw * rate
    price_usd = total_krw * KRW_TO_USD

    duty = get_customs_duty(price_krw * rate, cc, age)
    util = get_utilsbor(cc, hp, age, purpose)
    doc_fee = get_customs_doc_fee(price_krw * rate)

    base = price_rub + duty + util + doc_fee + BROKER_FEES + SERVICE_FEE
    total_vlad = base
    total_msk = base + AUTOVOZ_MSK

    return {
        "price_krw": price_krw,
        "total_krw": total_krw,
        "price_rub": price_rub,
        "price_usd": price_usd,
        "duty": duty,
        "util": util,
        "doc_fee": doc_fee,
        "broker": BROKER_FEES,
        "service": SERVICE_FEE,
        "autovoz": AUTOVOZ_MSK,
        "total_vlad": total_vlad,
        "total_msk": total_msk,
        "cc": cc, "hp": hp, "age": age, "purpose": purpose,
        "rate": rate,
    }

def format_result(r: dict) -> str:
    age_str = {"new": "до 3 лет", "old": "3–5 лет", "older": "старше 5 лет"}.get(r["age"], "—")
    purpose_str = "физлицо" if r["purpose"] == "personal" else "юрлицо"
    return (
        f"🚗 Расчёт стоимости\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Цена авто: ₩{r['price_krw']:,}\n"
        f"+ Расходы Корея/фрахт: ₩{2_000_000:,}\n"
        f"Итого KRW: ₩{r['total_krw']:,}\n"
        f"В рублях: {fmt(r['price_rub'])}\n"
        f"USDT ≈ ${round(r['price_usd']):,}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Объём: {r['cc']} см³ | Мощность: {r['hp']} л.с.\n"
        f"Возраст: {age_str} | {purpose_str}\n"
        f"Курс: 1 ₽ = {round(1 / r['rate'], 1)} ₩\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Таможенная пошлина: {fmt(r['duty'])}\n"
        f"Таможенный сбор: {fmt(r['doc_fee'])}\n"
        f"Утилизационный сбор: {fmt(r['util'])}\n"
        f"Брокер + СВХ + лаборатория: {fmt(r['broker'])}\n"
        f"Договор за услугу: {fmt(r['service'])}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🏁 До Владивостока: {fmt(r['total_vlad'])}\n"
        f"🏁 До Москвы: {fmt(r['total_msk'])}"
    )

# ── Клавиатуры ───────────────────────────────────────────────────────────────
def age_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("До 3 лет", callback_data="age_new"),
         InlineKeyboardButton("3–5 лет", callback_data="age_old"),
         InlineKeyboardButton("Старше 5 лет", callback_data="age_older")],
    ])

def purpose_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Физлицо (для себя)", callback_data="purpose_personal"),
         InlineKeyboardButton("Юрлицо", callback_data="purpose_commercial")],
    ])

def confirm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Всё верно", callback_data="calc"),
         InlineKeyboardButton("🔄 Заново", callback_data="restart")],
    ])

# ── Хэндлеры ────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🚗 *Калькулятор авто из Кореи в Россию*\n\n"
        "Отправь голосовым или текстом параметры авто:\n\n"
        "Например: _«38 миллионов вон, 1500 кубиков, 136 лошадей, 4 года»_\n\n"
        "Или используй /manual для пошагового ввода.",
        parse_mode="Markdown"
    )
    return WAITING_INPUT

async def receive_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    file = await update.message.voice.get_file()
    path = f"/tmp/calc_{update.message.message_id}.ogg"
    await file.download_to_drive(path)
    msg = await update.message.reply_text("⏳ Распознаю...")
    text = await transcribe_voice(path)
    os.remove(path)
    await msg.edit_text(f"🗣 _{text}_\n\n⏳ Считаю...", parse_mode="Markdown")
    return await process_text(update, ctx, text, msg)

async def receive_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    msg = await update.message.reply_text("⏳ Считаю...")
    return await process_text(update, ctx, text, msg)

async def process_text(update, ctx, text, msg):
    try:
        params = await extract_params(text)
    except Exception as e:
        await msg.edit_text(f"❌ Не смог разобрать параметры. Попробуй ещё раз.\n\n{e}")
        return WAITING_INPUT

    ctx.user_data["params"] = params

    age_labels = {"new": "до 3 лет", "old": "3–5 лет", "older": "старше 5 лет"}
    age_str = age_labels.get(params.get("age") or "", "?")

    summary = (
        f"Цена: ₩{int(params.get('price_krw') or 0):,}\n"
        f"Объём: {params.get('engine_cc') or '?'} см³\n"
        f"Мощность: {params.get('engine_hp') or '?'} л.с.\n"
        f"Возраст: {age_str}\n"
    )

    # Если нет объёма — просим ввести текстом
    if not params.get("engine_cc"):
        await msg.edit_text(
            f"Понял:\n{summary}\n"
            f"Введи объём двигателя в см³ (например: 1497):"
        )
        ctx.user_data["waiting_cc"] = True
        return WAITING_INPUT

    # Если нет мощности — просим ввести текстом
    if not params.get("engine_hp"):
        await msg.edit_text(
            f"Понял:\n{summary}\n"
            f"Введи мощность в л.с. (например: 136):"
        )
        ctx.user_data["waiting_hp"] = True
        return WAITING_INPUT

    if not params.get("age"):
        await msg.edit_text(f"Понял:\n{summary}\nВыбери возраст авто:", reply_markup=age_keyboard())
        return WAITING_INPUT

    if not params.get("purpose"):
        await msg.edit_text(f"Понял:\n{summary}\nДля кого ввозим?", reply_markup=purpose_keyboard())
        return WAITING_INPUT

    await msg.edit_text(f"Проверь параметры:\n\n{summary}", reply_markup=confirm_keyboard())
    return CONFIRM

async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("cc_"):
        cc_map = {"cc_1000": 900, "cc_1500": 1300, "cc_2000": 1800,
                  "cc_2500": 2200, "cc_3000": 2800, "cc_3500": 3500}
        ctx.user_data.setdefault("params", {})["engine_cc"] = str(cc_map.get(data, 1500))
        params = ctx.user_data["params"]
        age_str = {"new":"до 3 лет","old":"3–5 лет","older":"старше 5 лет"}.get(params.get("age",""), "?")
        summary = (f"Цена: ₩{int(params.get('price_krw') or 0):,}\n"
                   f"Объём: {params.get('engine_cc','?')} см³\n"
                   f"Мощность: {params.get('engine_hp') or '?'} л.с.\n"
                   f"Возраст: {age_str}\n")
        if not params.get("engine_hp"):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("до 100 л.с.", callback_data="hp_90"),
                 InlineKeyboardButton("100–130", callback_data="hp_120"),
                 InlineKeyboardButton("130–160", callback_data="hp_150")],
                [InlineKeyboardButton("160–200", callback_data="hp_180"),
                 InlineKeyboardButton("200–250", callback_data="hp_220"),
                 InlineKeyboardButton("более 250", callback_data="hp_280")],
            ])
            await query.message.edit_text(f"Понял:\n{summary}\nВыбери мощность:", reply_markup=keyboard)
            return WAITING_INPUT
        if not params.get("age"):
            await query.message.edit_text(f"Понял:\n{summary}\nВыбери возраст:", reply_markup=age_keyboard())
            return WAITING_INPUT
        await query.message.edit_text(f"Проверь параметры:\n\n{summary}", reply_markup=confirm_keyboard())
        return CONFIRM

    elif data.startswith("hp_"):
        hp_map = {"hp_90": 85, "hp_120": 115, "hp_150": 145,
                  "hp_180": 175, "hp_220": 210, "hp_280": 260}
        ctx.user_data.setdefault("params", {})["engine_hp"] = str(hp_map.get(data, 136))
        params = ctx.user_data["params"]
        age_str = {"new":"до 3 лет","old":"3–5 лет","older":"старше 5 лет"}.get(params.get("age",""), "?")
        summary = (f"Цена: ₩{int(params.get('price_krw') or 0):,}\n"
                   f"Объём: {params.get('engine_cc','?')} см³\n"
                   f"Мощность: {params.get('engine_hp','?')} л.с.\n"
                   f"Возраст: {age_str}\n")
        if not params.get("age"):
            await query.message.edit_text(f"Понял:\n{summary}\nВыбери возраст:", reply_markup=age_keyboard())
            return WAITING_INPUT
        await query.message.edit_text(f"Проверь параметры:\n\n{summary}", reply_markup=confirm_keyboard())
        return CONFIRM

    elif data.startswith("age_"):
        ctx.user_data.setdefault("params", {})["age"] = data.replace("age_", "")
        params = ctx.user_data["params"]
        if not params.get("purpose"):
            await query.message.edit_text("Для кого ввозим?", reply_markup=purpose_keyboard())
            return WAITING_INPUT
        age_str = {"new":"до 3 лет","old":"3–5 лет","older":"старше 5 лет"}.get(params.get("age",""), "?")
        summary = (
            f"Цена: ₩{int(params.get('price_krw') or 0):,}\n"
            f"Объём: {params.get('engine_cc','?')} см³\n"
            f"Мощность: {params.get('engine_hp','?')} л.с.\n"
            f"Возраст: {age_str}\n"
        )
        await query.message.edit_text(f"Проверь параметры:\n\n{summary}", reply_markup=confirm_keyboard())
        return CONFIRM

    elif data.startswith("purpose_"):
        ctx.user_data.setdefault("params", {})["purpose"] = data.replace("purpose_", "")
        params = ctx.user_data["params"]
        age_str = {"new":"до 3 лет","old":"3–5 лет","older":"старше 5 лет"}.get(params.get("age",""), "?")
        summary = (
            f"Цена: ₩{int(params.get('price_krw') or 0):,}\n"
            f"Объём: {params.get('engine_cc','?')} см³\n"
            f"Мощность: {params.get('engine_hp','?')} л.с.\n"
            f"Возраст: {age_str}\n"
        )
        await query.message.edit_text(f"Проверь параметры:\n\n{summary}", reply_markup=confirm_keyboard())
        return CONFIRM

    elif data == "calc":
        params = ctx.user_data.get("params", {})
        result = calculate(params)
        ctx.user_data["result"] = result
        text = format_result(result)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Новый расчёт", callback_data="restart"),
             InlineKeyboardButton("📊 Другой курс", callback_data="change_rate")],
        ])
        await query.message.edit_text(text, reply_markup=keyboard)
        return CONFIRM

    elif data == "change_rate":
        await query.message.reply_text(
            "Введи курс KRW→RUB (например: 0.0540)\n"
            "или обратный — сколько вон за 1 рубль (например: 18.5):"
        )
        ctx.user_data["waiting_rate"] = True
        return WAITING_INPUT

    elif data == "restart":
        ctx.user_data.clear()
        await query.message.reply_text(
            "Отправь параметры голосом или текстом.\n\n"
            "Например: _«38 миллионов вон, 1500 кубиков, 136 лошадей, 4 года»_",
            parse_mode="Markdown"
        )
        return WAITING_INPUT

async def handle_rate_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data.get("waiting_cc"):
        try:
            cc = int(re.findall(r"\d+", update.message.text)[0])
            ctx.user_data["waiting_cc"] = False
            ctx.user_data.setdefault("params", {})["engine_cc"] = str(cc)
            params = ctx.user_data["params"]
            age_labels = {"new": "до 3 лет", "old": "3–5 лет", "older": "старше 5 лет"}
            age_str = age_labels.get(params.get("age") or "", "?")
            summary = (f"Цена: ₩{int(params.get('price_krw') or 0):,}\n"
                       f"Объём: {cc} см³\n"
                       f"Мощность: {params.get('engine_hp') or '?'} л.с.\n"
                       f"Возраст: {age_str}\n")
            if not params.get("engine_hp"):
                await update.message.reply_text(f"Понял:\n{summary}\nВведи мощность в л.с. (например: 136):")
                ctx.user_data["waiting_hp"] = True
                return WAITING_INPUT
            if not params.get("age"):
                await update.message.reply_text(f"Понял:\n{summary}\nВыбери возраст:", reply_markup=age_keyboard())
                return WAITING_INPUT
            await update.message.reply_text(f"Проверь параметры:\n\n{summary}", reply_markup=confirm_keyboard())
            return CONFIRM
        except:
            await update.message.reply_text("Введи число, например: 1497")
            return WAITING_INPUT

    if ctx.user_data.get("waiting_hp"):
        try:
            hp = int(re.findall(r"\d+", update.message.text)[0])
            ctx.user_data["waiting_hp"] = False
            ctx.user_data.setdefault("params", {})["engine_hp"] = str(hp)
            params = ctx.user_data["params"]
            age_labels = {"new": "до 3 лет", "old": "3–5 лет", "older": "старше 5 лет"}
            age_str = age_labels.get(params.get("age") or "", "?")
            summary = (f"Цена: ₩{int(params.get('price_krw') or 0):,}\n"
                       f"Объём: {params.get('engine_cc','?')} см³\n"
                       f"Мощность: {hp} л.с.\n"
                       f"Возраст: {age_str}\n")
            if not params.get("age"):
                await update.message.reply_text(f"Понял:\n{summary}\nВыбери возраст:", reply_markup=age_keyboard())
                return WAITING_INPUT
            await update.message.reply_text(f"Проверь параметры:\n\n{summary}", reply_markup=confirm_keyboard())
            return CONFIRM
        except:
            await update.message.reply_text("Введи число, например: 136")
            return WAITING_INPUT

    if ctx.user_data.get("waiting_rate"):
        try:
            val = float(update.message.text.strip().replace(",", "."))
            # Если число больше 1 — значит это вон за рубль, инвертируем
            rate = 1 / val if val > 1 else val
            ctx.user_data["waiting_rate"] = False
            params = ctx.user_data.get("params", {})
            result = calculate(params, krw_rub=rate)
            ctx.user_data["result"] = result
            text = format_result(result)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Новый расчёт", callback_data="restart"),
                 InlineKeyboardButton("📊 Другой курс", callback_data="change_rate")],
            ])
            await update.message.reply_text(text, reply_markup=keyboard)
            return CONFIRM
        except:
            await update.message.reply_text("Не понял курс. Введи число, например: 0.0540")
            return WAITING_INPUT
    return await receive_text(update, ctx)

async def manual_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["manual"] = True
    await update.message.reply_text(
        "Введи цену авто в вонах (только цифры):\nНапример: 39900000"
    )
    ctx.user_data["step"] = "price"
    return WAITING_INPUT

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Отменено. Отправь /start чтобы начать заново.")
    return WAITING_INPUT

# ── Запуск ───────────────────────────────────────────────────────────────────
def main():
    import time
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30)
    app = Application.builder().token(TELEGRAM_TOKEN).request(request).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("manual", manual_start),
        ],
        states={
            WAITING_INPUT: [
                MessageHandler(filters.VOICE, receive_voice),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rate_input),
                CallbackQueryHandler(button_callback),
            ],
            CONFIRM: [
                CallbackQueryHandler(button_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rate_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
    )

    app.add_handler(conv)
    print("📊 Calc Bot запущен")
    app.run_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
