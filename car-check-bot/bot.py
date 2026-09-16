import os
import re
import json
import asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import groq

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_API_KEY   = os.environ["GROQ_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
groq_client    = groq.Groq(api_key=GROQ_API_KEY)

# ── Состояния разговора ───────────────────────────────────────────────────────
(WAITING_LINK, WAITING_PLATE, WAITING_PRICE,
 WAITING_KEYS, WAITING_CONDITION, WAITING_KESANSO,
 WAITING_KESANSO_INPUT, WAITING_MEDOBI, WAITING_MEDOBI_INPUT,
 WAITING_MALSO, WAITING_MALSO_INPUT, CONFIRM) = range(12)

# ── Парсинг Encar ─────────────────────────────────────────────────────────────
async def parse_encar(url: str) -> dict:
    """Парсим данные авто с Encar через API."""
    try:
        # Извлекаем carid из URL
        match = re.search(r'/detail/(\d+)', url)
        if not match:
            return {}
        car_id = match.group(1)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.encar.com/search/car/list/premium?count=1&q=(Id:{car_id})",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                return {}
            data = resp.json()
            cars = data.get("SearchResults", [])
            if not cars:
                return {}
            car = cars[0]

            name = f"{car.get('Manufacturer', '')} {car.get('Model', '')} {car.get('Badge', '')}".strip()
            city_raw = car.get("ServiceCoporation", "") or car.get("OfficeCityState", "") or ""

            return {
                "name": name or "—",
                "city": translate_city(city_raw),
            }
    except Exception:
        return {}

def translate_city(raw: str) -> str:
    """Переводим корейский город на русский."""
    cities = {
        "서울": "Сеул", "부산": "Пусан", "인천": "Инчхон", "대구": "Тэгу",
        "대전": "Тэджон", "광주": "Кванджу", "수원": "Сувон", "울산": "Ульсан",
        "성남": "Соннам", "용인": "Йонъин", "전주": "Чонджу", "창원": "Чханвон",
        "고양": "Коян", "안산": "Ансан", "안양": "Анян", "남양주": "Намянджу",
        "화성": "Хвасон", "평택": "Пхёнтхэк", "의정부": "Ыйджонбу",
        "시흥": "Сихын", "파주": "Паджу", "김포": "Кимпхо", "광명": "Кванмён",
        "경기": "Кёнги", "경남": "Кённам", "경북": "Кёнбук", "충남": "Чхунчхам",
        "충북": "Чхунбук", "전남": "Чоннам", "전북": "Чонбук", "강원": "Канвон",
        "제주": "Чеджу", "구리": "Гури", "하남": "Хасон", "오산": "Осан",
        "청주": "Чонджу", "군포": "Кунпхо", "의왕": "Ыйван", "양주": "Янджу",
    }
    for kr, ru in cities.items():
        if kr in raw:
            return ru
    return raw if raw else "—"

# ── Форматирование ────────────────────────────────────────────────────────────
def get_last4(plate: str) -> str:
    if not plate or plate == "—":
        return ""
    digits = re.findall(r"\d+", plate)
    if len(digits) >= 2:
        return digits[-1][-4:]
    elif digits:
        return digits[-1][-4:]
    return ""

def format_result(data: dict) -> str:
    name = data.get("name", "—")
    plate = data.get("plate", "—")
    last4 = get_last4(plate)
    name_with_plate = f"{name} {last4}".strip() if last4 else name

    price = data.get("price", "—")
    try:
        price_fmt = f"{int(price.replace(',','').replace(' ','')):,}" if price != "—" else "—"
    except:
        price_fmt = price

    medobi = data.get("medobi", "—")
    try:
        medobi_fmt = f"{int(medobi.replace(',','').replace(' ','')):,}" if medobi not in ("—", "нет") else medobi
    except:
        medobi_fmt = medobi

    lines = [
        data.get("url", ""),
        "",
        name_with_plate,
        plate,
        "",
        price_fmt,
        "",
        f"🔑 {data.get('keys', '—')}",
        "",
        f"Состояние: {data.get('condition', '—')}",
        "",
        f"Кесансо: {data.get('kesanso', '—')}",
        "",
        f"Медоби: {medobi_fmt}",
        "",
        f"Мальсо: {data.get('malso', '—')}",
        "",
        f"📍 {data.get('city', '—')}",
        "",
        "⚠️ Перед осмотром обязательно связаться с дилером",
    ]
    return "\n".join(lines)

# ── Кнопки ────────────────────────────────────────────────────────────────────
def keys_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔑 1", callback_data="keys_1"),
        InlineKeyboardButton("🔑 2", callback_data="keys_2"),
    ]])

def condition_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Чистая", callback_data="cond_clean"),
        InlineKeyboardButton("🔍 Надо смотреть", callback_data="cond_check"),
    ]])

def kesanso_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("100%", callback_data="kes_100"),
        InlineKeyboardButton("Нет", callback_data="kes_no"),
        InlineKeyboardButton("Ввести сумму", callback_data="kes_input"),
    ]])

def medobi_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("440,000", callback_data="med_440"),
        InlineKeyboardButton("450,000", callback_data="med_450"),
        InlineKeyboardButton("Другое", callback_data="med_input"),
    ]])

def malso_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Сразу", callback_data="mal_now"),
        InlineKeyboardButton("Завтра", callback_data="mal_tomorrow"),
    ],[
        InlineKeyboardButton("1-2 недели", callback_data="mal_2weeks"),
        InlineKeyboardButton("Другое", callback_data="mal_input"),
    ]])

def confirm_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Отправить", callback_data="send"),
        InlineKeyboardButton("🔄 Заново", callback_data="restart"),
    ]])

# ── Хэндлеры ─────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Отправь ссылку на авто.")
    return WAITING_LINK

async def receive_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "http" not in text:
        await update.message.reply_text("Не вижу ссылку. Попробуй ещё раз.")
        return WAITING_LINK

    ctx.user_data.clear()
    ctx.user_data["url"] = text.strip()

    msg = await update.message.reply_text("⏳ Загружаю данные авто...")

    parsed = await parse_encar(text)
    ctx.user_data["name"] = parsed.get("name", "—")
    ctx.user_data["city"] = parsed.get("city", "—")

    name = ctx.user_data["name"]
    city = ctx.user_data["city"]
    info = f"🚗 *{name}*" if name != "—" else "🚗 Авто"
    if city != "—":
        info += f"  📍 {city}"

    await msg.edit_text(
        f"{info}\n\nВведи *номер авто* (например: 256수7232)",
        parse_mode="Markdown"
    )
    return WAITING_PLATE

async def receive_plate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["plate"] = update.message.text.strip()
    await update.message.reply_text("Введи *цену* в вонах (например: 26500000)", parse_mode="Markdown")
    return WAITING_PRICE

async def receive_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["price"] = update.message.text.strip()
    await update.message.reply_text("Выбери количество ключей:", reply_markup=keys_keyboard())
    return WAITING_KEYS

async def keys_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["keys"] = "1" if query.data == "keys_1" else "2"
    await query.message.reply_text("Состояние кузова:", reply_markup=condition_keyboard())
    return WAITING_CONDITION

async def condition_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["condition"] = "чистая" if query.data == "cond_clean" else "надо смотреть"
    await query.message.reply_text("Кесансо:", reply_markup=kesanso_keyboard())
    return WAITING_KESANSO

async def kesanso_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "kes_100":
        ctx.user_data["kesanso"] = "100%"
        await query.message.reply_text("Медоби:", reply_markup=medobi_keyboard())
        return WAITING_MEDOBI
    elif query.data == "kes_no":
        ctx.user_data["kesanso"] = "нет"
        await query.message.reply_text("Медоби:", reply_markup=medobi_keyboard())
        return WAITING_MEDOBI
    else:
        await query.message.reply_text("Введи сумму кесансо:")
        return WAITING_KESANSO_INPUT

async def kesanso_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["kesanso"] = update.message.text.strip()
    await update.message.reply_text("Медоби:", reply_markup=medobi_keyboard())
    return WAITING_MEDOBI

async def medobi_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "med_440":
        ctx.user_data["medobi"] = "440000"
        await query.message.reply_text("Мальсо:", reply_markup=malso_keyboard())
        return WAITING_MALSO
    elif query.data == "med_450":
        ctx.user_data["medobi"] = "450000"
        await query.message.reply_text("Мальсо:", reply_markup=malso_keyboard())
        return WAITING_MALSO
    else:
        await query.message.reply_text("Введи сумму медоби:")
        return WAITING_MEDOBI_INPUT

async def medobi_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["medobi"] = update.message.text.strip()
    await update.message.reply_text("Мальсо:", reply_markup=malso_keyboard())
    return WAITING_MALSO

async def malso_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mapping = {
        "mal_now": "сразу",
        "mal_tomorrow": "завтра",
        "mal_2weeks": "1-2 недели",
    }
    if query.data in mapping:
        ctx.user_data["malso"] = mapping[query.data]
        await show_confirm(query.message, ctx)
        return CONFIRM
    else:
        await query.message.reply_text("Введи дату или срок мальсо:")
        return WAITING_MALSO_INPUT

async def malso_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["malso"] = update.message.text.strip()
    await show_confirm(update.message, ctx)
    return CONFIRM

async def show_confirm(message, ctx: ContextTypes.DEFAULT_TYPE):
    result = format_result(ctx.user_data)
    ctx.user_data["final_result"] = result
    await message.reply_text(
        f"```\n{result}\n```",
        parse_mode="Markdown",
        reply_markup=confirm_keyboard(),
    )

async def confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "send":
        result = ctx.user_data.get("final_result") or format_result(ctx.user_data)
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

# ── Запуск ────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & filters.Regex(r"http"), receive_link),
        ],
        states={
            WAITING_LINK: [MessageHandler(filters.TEXT, receive_link)],
            WAITING_PLATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_plate)],
            WAITING_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_price)],
            WAITING_KEYS: [CallbackQueryHandler(keys_callback, pattern="^keys_")],
            WAITING_CONDITION: [CallbackQueryHandler(condition_callback, pattern="^cond_")],
            WAITING_KESANSO: [CallbackQueryHandler(kesanso_callback, pattern="^kes_")],
            WAITING_KESANSO_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, kesanso_input)],
            WAITING_MEDOBI: [CallbackQueryHandler(medobi_callback, pattern="^med_")],
            WAITING_MEDOBI_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, medobi_input)],
            WAITING_MALSO: [CallbackQueryHandler(malso_callback, pattern="^mal_")],
            WAITING_MALSO_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, malso_input)],
            CONFIRM: [CallbackQueryHandler(confirm_callback, pattern="^(send|restart)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_message=False,
    )

    app.add_handler(conv)
    print("🚗 Car Check Bot запущен")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
