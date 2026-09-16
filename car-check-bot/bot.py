import os
import re
import asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# ── Состояния ─────────────────────────────────────────────────────────────────
WAITING_LINK, WAITING_TEXT_INPUT, FILLING, CONFIRM = range(4)

# ── Перевод городов ───────────────────────────────────────────────────────────
CITY_MAP = {
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
    "천안": "Чхонан", "아산": "Асан", "원주": "Вонджу", "춘천": "Чхунчхон",
    "구미": "Куми", "포항": "Пхохан", "진주": "Чинджу", "목포": "Мокпхо",
    "여수": "Ёсу", "순천": "Сунчхон",
}

def translate_city(raw: str) -> str:
    for kr, ru in CITY_MAP.items():
        if kr in raw:
            return ru
    return raw if raw else "—"

# ── Перевод марок/моделей ─────────────────────────────────────────────────────
BRAND_MAP = {
    "기아": "KIA", "현대": "Hyundai", "제네시스": "Genesis",
    "쉐보레": "Chevrolet", "르노": "Renault", "삼성": "Samsung",
    "쌍용": "SsangYong", "벤츠": "Mercedes", "아우디": "Audi",
    "폭스바겐": "Volkswagen", "볼보": "Volvo", "렉서스": "Lexus",
    "토요타": "Toyota", "혼다": "Honda", "닛산": "Nissan",
    "포드": "Ford", "지프": "Jeep", "랜드로버": "Land Rover",
    "포르쉐": "Porsche", "미니": "MINI",
}
MODEL_MAP = {
    "스포티지": "Sportage", "쏘렌토": "Sorento", "카니발": "Carnival",
    "팰리세이드": "Palisade", "아반떼": "Avante", "소나타": "Sonata",
    "그랜저": "Grandeur", "투싼": "Tucson", "싼타페": "Santa Fe",
    "스타렉스": "Starex", "코나": "Kona", "아이오닉": "Ioniq",
    "트레일블레이저": "Trailblazer", "티볼리": "Tivoli", "렉스턴": "Rexton",
    "C클래스": "C-класс", "E클래스": "E-класс", "S클래스": "S-класс",
    "5시리즈": "5 Series", "3시리즈": "3 Series", "7시리즈": "7 Series",
}
NOISE = ["세대", "중고차", "프레스티지", "익스클루시브", "모던", "프리미엄", "럭셔리"]

def translate_name(raw: str) -> str:
    if not raw:
        return "—"
    result = raw
    for kr, en in {**BRAND_MAP, **MODEL_MAP}.items():
        result = result.replace(kr, en)
    for w in NOISE:
        result = re.sub(rf'\d*{w}', '', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result or "—"

# ── Парсинг Encar API ─────────────────────────────────────────────────────────
async def parse_encar(car_id: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": f"https://fem.encar.com/cars/detail/{car_id}",
    }
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(
                f"https://api.encar.com/search/car/list/mobile?count=1&q=(Id:{car_id})",
                headers=headers
            )
            if resp.status_code == 200:
                cars = resp.json().get("SearchResults", [])
                if cars:
                    c = cars[0]
                    name_raw = f"{c.get('Manufacturer','')} {c.get('Model','')} {c.get('Badge','')}".strip()
                    city_raw = c.get("OfficeCityState", "") or c.get("ServiceCoporation", "") or ""
                    return {
                        "name": translate_name(name_raw) or "—",
                        "city": translate_city(city_raw),
                    }
    except Exception:
        pass
    return {}

# ── Форматирование ────────────────────────────────────────────────────────────
def fmt_money(val: str) -> str:
    if not val or val in ("—", "нет", "Нет"):
        return val or "—"
    nums = re.findall(r"\d+", val.replace(",", "").replace(" ", ""))
    if nums:
        try:
            return f"{int(''.join(nums)):,}"
        except:
            pass
    return val

def get_last4(plate: str) -> str:
    if not plate or plate == "—":
        return ""
    digits = re.findall(r"\d+", plate)
    return digits[-1][-4:] if digits else ""

def format_result(data: dict) -> str:
    name  = data.get("name", "—")
    plate = data.get("plate", "—")
    last4 = get_last4(plate)
    lines = [
        data.get("url", ""),
        "",
        f"{name} {last4}".strip() if last4 else name,
        plate,
        "",
        fmt_money(data.get("price", "—")),
        "",
        f"🔑 {data.get('keys', '—')}",
        "",
        f"Состояние: {data.get('condition', '—')}",
        "",
        f"Кесансо: {fmt_money(data.get('kesanso', '—'))}",
        "",
        f"Медоби: {fmt_money(data.get('medobi', '—'))}",
        "",
        f"Мальсо: {data.get('malso', '—')}",
        "",
        f"📍 {data.get('city', '—')}",
        "",
        "⚠️ Перед осмотром обязательно связаться с дилером",
    ]
    return "\n".join(lines)

# ── Форма (текст + кнопки) ────────────────────────────────────────────────────
def build_form_text(d: dict) -> str:
    name  = d.get("name", "—")
    city  = d.get("city", "—")
    plate = d.get("plate", "—")
    price = d.get("price", "—")
    return "\n".join([
        f"🚗 *{name}*  📍 {city}",
        "",
        f"Номер: `{plate}`",
        f"Цена: `{fmt_money(price)}`",
        f"Ключи: {d.get('keys', '—')}",
        f"Состояние: {d.get('condition', '—')}",
        f"Кесансо: {fmt_money(d.get('kesanso', '—'))}",
        f"Медоби: {fmt_money(d.get('medobi', '—'))}",
        f"Мальсо: {d.get('malso', '—')}",
    ])

def build_keyboard(d: dict) -> InlineKeyboardMarkup:
    def chk(key, val):
        return " ✅" if d.get(key) == val else ""

    rows = [
        # Ключи
        [
            InlineKeyboardButton(f"🔑 1{chk('keys','1')}", callback_data="keys_1"),
            InlineKeyboardButton(f"🔑 2{chk('keys','2')}", callback_data="keys_2"),
        ],
        # Состояние
        [
            InlineKeyboardButton(f"✅ Чистая{chk('condition','чистая')}", callback_data="cond_clean"),
            InlineKeyboardButton(f"🔍 Надо смотреть{chk('condition','надо смотреть')}", callback_data="cond_check"),
        ],
        # Кесансо
        [
            InlineKeyboardButton(f"Кесансо 100%{chk('kesanso','100%')}", callback_data="kes_100"),
            InlineKeyboardButton(f"Нет{chk('kesanso','нет')}", callback_data="kes_no"),
            InlineKeyboardButton("Кесансо ↩", callback_data="kes_input"),
        ],
        # Медоби
        [
            InlineKeyboardButton(f"440,000{chk('medobi','440000')}", callback_data="med_440"),
            InlineKeyboardButton(f"450,000{chk('medobi','450000')}", callback_data="med_450"),
            InlineKeyboardButton(f"330,000{chk('medobi','330000')}", callback_data="med_330"),
            InlineKeyboardButton("Медоби ↩", callback_data="med_input"),
        ],
        # Мальсо
        [
            InlineKeyboardButton(f"Сразу{chk('malso','сразу')}", callback_data="mal_now"),
            InlineKeyboardButton(f"Завтра{chk('malso','завтра')}", callback_data="mal_tomorrow"),
            InlineKeyboardButton(f"1-2 нед{chk('malso','1-2 недели')}", callback_data="mal_2weeks"),
            InlineKeyboardButton("Мальсо ↩", callback_data="mal_input"),
        ],
    ]

    # Кнопка отправить — только если все поля заполнены
    if all(d.get(k) for k in ["plate", "price", "keys", "condition", "kesanso", "medobi", "malso"]):
        rows.append([InlineKeyboardButton("✅ Отправить", callback_data="send")])

    rows.append([InlineKeyboardButton("🔄 Заново", callback_data="restart")])
    return InlineKeyboardMarkup(rows)

async def refresh_form(ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await ctx.bot.edit_message_text(
            chat_id=ctx.user_data["form_chat"],
            message_id=ctx.user_data["form_msg"],
            text=build_form_text(ctx.user_data),
            parse_mode="Markdown",
            reply_markup=build_keyboard(ctx.user_data),
        )
    except Exception:
        pass

# ── Хэндлеры ─────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Отправь ссылку на Энкар.")
    return WAITING_LINK

async def receive_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if "http" not in text:
        await update.message.reply_text("Не вижу ссылку. Попробуй ещё раз.")
        return WAITING_LINK

    ctx.user_data.clear()
    ctx.user_data["url"] = text

    match = re.search(r'/detail/(\d+)', text)
    car_id = match.group(1) if match else None

    msg = await update.message.reply_text("⏳ Загружаю данные авто...")

    parsed = await parse_encar(car_id) if car_id else {}
    ctx.user_data["name"] = parsed.get("name", "—")
    ctx.user_data["city"] = parsed.get("city", "—")

    name_line = f"*{ctx.user_data['name']}*" if ctx.user_data['name'] != "—" else "авто"
    city_line = f"  📍 {ctx.user_data['city']}" if ctx.user_data['city'] != "—" else ""

    await msg.edit_text(
        f"🚗 {name_line}{city_line}\n\nВведи *номер авто* (например: 256수7232):",
        parse_mode="Markdown"
    )
    ctx.user_data["waiting_for"] = "plate"
    return WAITING_TEXT_INPUT

async def receive_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = (update.message.text or "").strip()
    field = ctx.user_data.get("waiting_for")

    if field == "plate":
        ctx.user_data["plate"] = val
        await update.message.reply_text(
            "💰 Введи *цену* в вонах (например: 26500000):",
            parse_mode="Markdown"
        )
        ctx.user_data["waiting_for"] = "price"
        return WAITING_TEXT_INPUT

    elif field == "price":
        ctx.user_data["price"] = val
        ctx.user_data["waiting_for"] = None
        # Показываем форму с кнопками
        m = await update.message.reply_text(
            build_form_text(ctx.user_data),
            parse_mode="Markdown",
            reply_markup=build_keyboard(ctx.user_data),
        )
        ctx.user_data["form_msg"] = m.message_id
        ctx.user_data["form_chat"] = m.chat_id
        return FILLING

    elif field in ("kesanso_custom", "medobi_custom", "malso_custom"):
        key = field.replace("_custom", "")
        ctx.user_data[key] = val
        ctx.user_data["waiting_for"] = None
        await refresh_form(ctx)
        return FILLING

    return FILLING

async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    d = query.data

    if d == "restart":
        ctx.user_data.clear()
        await query.message.reply_text("Отправь ссылку на Энкар.")
        return WAITING_LINK

    if d == "send":
        result = format_result(ctx.user_data)
        await query.message.reply_text(result)
        ctx.user_data.clear()
        await query.message.reply_text("✅ Готово! Отправь новую ссылку.")
        return WAITING_LINK

    # Обновляем данные
    mapping = {
        "keys_1": ("keys", "1"), "keys_2": ("keys", "2"),
        "cond_clean": ("condition", "чистая"), "cond_check": ("condition", "надо смотреть"),
        "kes_100": ("kesanso", "100%"), "kes_no": ("kesanso", "нет"),
        "med_440": ("medobi", "440000"), "med_450": ("medobi", "450000"),
        "med_330": ("medobi", "330000"),
        "mal_now": ("malso", "сразу"), "mal_tomorrow": ("malso", "завтра"),
        "mal_2weeks": ("malso", "1-2 недели"),
    }
    if d in mapping:
        key, val = mapping[d]
        ctx.user_data[key] = val
        ctx.user_data["form_msg"] = query.message.message_id
        ctx.user_data["form_chat"] = query.message.chat_id
        try:
            await query.message.edit_text(
                build_form_text(ctx.user_data),
                parse_mode="Markdown",
                reply_markup=build_keyboard(ctx.user_data),
            )
        except Exception:
            pass
        return FILLING

    # Кастомный ввод
    input_map = {
        "kes_input": ("kesanso_custom", "Введи сумму кесансо:"),
        "med_input": ("medobi_custom", "Введи сумму медоби:"),
        "mal_input": ("malso_custom", "Введи дату или срок мальсо:"),
    }
    if d in input_map:
        field, prompt = input_map[d]
        ctx.user_data["waiting_for"] = field
        ctx.user_data["form_msg"] = query.message.message_id
        ctx.user_data["form_chat"] = query.message.chat_id
        await query.message.reply_text(prompt)
        return WAITING_TEXT_INPUT

    return FILLING

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
            WAITING_TEXT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text_input),
                CallbackQueryHandler(button_callback),
            ],
            FILLING: [
                CallbackQueryHandler(button_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text_input),
            ],
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
