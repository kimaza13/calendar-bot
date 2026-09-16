import os
import re
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

WAITING_LINK, FILLING, WAITING_TEXT_INPUT = range(3)

# ── Города ────────────────────────────────────────────────────────────────────
CITY_MAP = {
    "서울": "Сеул", "부산": "Пусан", "인천": "Инчхон", "대구": "Тэгу",
    "대전": "Тэджон", "광주": "Кванджу", "수원": "Сувон", "울산": "Ульсан",
    "성남": "Соннам", "용인": "Йонъин", "전주": "Чонджу", "창원": "Чханвон",
    "고양": "Коян", "안산": "Ансан", "안양": "Анян", "남양주": "Намянджу",
    "화성": "Хвасон", "평택": "Пхёнтхэк", "의정부": "Ыйджонбу",
    "시흥": "Сихын", "파주": "Паджу", "김포": "Кимпхо", "광명": "Кванмён",
    "경기": "Кёнги", "경남": "Кённам", "경북": "Кёнбук",
    "충남": "Чхунчхам", "충북": "Чхунбук", "전남": "Чоннам",
    "전북": "Чонбук", "강원": "Канвон", "제주": "Чеджу",
    "구리": "Гури", "하남": "Хасон", "오산": "Осан", "청주": "Чонджу",
    "군포": "Кунпхо", "의왕": "Ыйван", "양주": "Янджу",
    "천안": "Чхонан", "아산": "Асан", "원주": "Вонджу",
    "춘천": "Чхунчхон", "구미": "Куми", "포항": "Пхохан",
    "진주": "Чинджу", "목포": "Мокпхо", "여수": "Ёсу", "순천": "Сунчхон",
}

def translate_city(raw: str) -> str:
    for kr, ru in CITY_MAP.items():
        if kr in raw:
            return ru
    return raw.strip() or "—"

# ── Марки/модели ──────────────────────────────────────────────────────────────
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
NOISE = ["세대", "중고차", "프레스티지", "익스클루시브", "모던", "프리미엄",
         "럭셔리", "하이브리드", "터보", "가솔린", "디젤", "내차팔기", "내차사기"]

def translate_name(raw: str) -> str:
    if not raw:
        return "—"
    result = raw
    for kr, en in {**BRAND_MAP, **MODEL_MAP}.items():
        result = result.replace(kr, en)
    for w in NOISE:
        result = re.sub(rf'\d*\s*{w}', ' ', result)
    result = re.sub(r'\b\d+\.\d+\b', '', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return result or "—"

# ── Encar API ─────────────────────────────────────────────────────────────────
async def parse_encar_api(car_id: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": f"https://fem.encar.com/cars/detail/{car_id}",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.encar.com/search/car/list/mobile?count=1&q=(Id:{car_id})",
                headers=headers,
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

# ── Деньги ────────────────────────────────────────────────────────────────────
def fmt_money(val: str) -> str:
    if not val or val in ("—", "нет"):
        return val or "—"
    nums = re.findall(r"\d+", val.replace(",", "").replace(" ", ""))
    if nums:
        try:
            return f"{int(''.join(nums)):,}"
        except Exception:
            pass
    return val

def get_last4(plate: str) -> str:
    if not plate or plate == "—":
        return ""
    digits = re.findall(r"\d+", plate)
    return digits[-1][-4:] if digits else ""

# ── Итоговая карточка ─────────────────────────────────────────────────────────
def format_result(d: dict) -> str:
    name  = d.get("name", "—")
    plate = d.get("plate", "—")
    last4 = get_last4(plate)
    return "\n".join([
        d.get("url", ""),
        "",
        f"{name} {last4}".strip() if last4 else name,
        plate,
        "",
        fmt_money(d.get("price", "—")),
        "",
        f"🔑 {d.get('keys', '—')}",
        "",
        f"Состояние: {d.get('condition', '—')}",
        "",
        f"Кесансо: {fmt_money(d.get('kesanso', '—'))}",
        "",
        f"Медоби: {fmt_money(d.get('medobi', '—'))}",
        "",
        f"Мальсо: {d.get('malso', '—')}",
        "",
        f"📍 {d.get('city', '—')}",
        "",
        "⚠️ Перед осмотром обязательно связаться с дилером",
    ])

# ── Форма ─────────────────────────────────────────────────────────────────────
def val(d, key, fmt=False):
    v = d.get(key)
    if not v:
        return "—"
    return fmt_money(v) if fmt else v

def dot(d, key, target):
    """Галочка если выбрано."""
    return " ✅" if d.get(key) == target else ""

def build_form(d: dict):
    name  = val(d, "name")
    plate = val(d, "plate")
    price = val(d, "price", fmt=True)
    keys  = val(d, "keys")
    cond  = val(d, "condition")
    kes   = val(d, "kesanso", fmt=True)
    med   = val(d, "medobi", fmt=True)
    mal   = val(d, "malso")
    city  = val(d, "city")

    text = (
        f"🚗 *Марка и модель:* {name}\n"
        f"🔢 *Номер:* `{plate}`\n"
        f"💵 *Цена:* `{price}`\n"
        f"🔑 *Ключи:* {keys}\n"
        f"🚘 *Состояние:* {cond}\n"
        f"📋 *Кесансо:* {kes}\n"
        f"💰 *Медоби:* {med}\n"
        f"📅 *Мальсо:* {mal}\n"
        f"📍 *Город:* {city}"
    )

    rows = [
        # Марка
        [InlineKeyboardButton(f"🚗 Марка и модель{' ✅' if d.get('name') and d.get('name') != '—' else ' ✏️'}", callback_data="edit_name")],
        # Номер
        [InlineKeyboardButton(f"🔢 Номер авто{' ✅' if d.get('plate') else ' ✏️'}", callback_data="edit_plate")],
        # Цена
        [InlineKeyboardButton(f"💵 Цена{' ✅' if d.get('price') else ' ✏️'}", callback_data="edit_price")],
        # Ключи
        [
            InlineKeyboardButton(f"🔑 1{dot(d,'keys','1')}", callback_data="keys_1"),
            InlineKeyboardButton(f"🔑 2{dot(d,'keys','2')}", callback_data="keys_2"),
        ],
        # Состояние
        [
            InlineKeyboardButton(f"✅ Чистая{dot(d,'condition','чистая')}", callback_data="cond_clean"),
            InlineKeyboardButton(f"🔍 Надо смотреть{dot(d,'condition','надо смотреть')}", callback_data="cond_check"),
        ],
        # Кесансо
        [
            InlineKeyboardButton(f"100%{dot(d,'kesanso','100%')}", callback_data="kes_100"),
            InlineKeyboardButton(f"Нет{dot(d,'kesanso','нет')}", callback_data="kes_no"),
            InlineKeyboardButton("Ввести сумму", callback_data="kes_input"),
        ],
        # Медоби
        [
            InlineKeyboardButton(f"440,000{dot(d,'medobi','440000')}", callback_data="med_440"),
            InlineKeyboardButton(f"450,000{dot(d,'medobi','450000')}", callback_data="med_450"),
            InlineKeyboardButton(f"330,000{dot(d,'medobi','330000')}", callback_data="med_330"),
            InlineKeyboardButton("Другое", callback_data="med_input"),
        ],
        # Мальсо
        [
            InlineKeyboardButton(f"Сразу{dot(d,'malso','сразу')}", callback_data="mal_now"),
            InlineKeyboardButton(f"Завтра{dot(d,'malso','завтра')}", callback_data="mal_tomorrow"),
            InlineKeyboardButton(f"1-2 нед{dot(d,'malso','1-2 недели')}", callback_data="mal_2weeks"),
            InlineKeyboardButton("Другое", callback_data="mal_input"),
        ],
        # Город
        [InlineKeyboardButton(f"📍 Город{' ✅' if d.get('city') and d.get('city') != '—' else ' ✏️'}", callback_data="edit_city")],
    ]

    # Отправить — только когда всё заполнено
    required = ["name", "plate", "price", "keys", "condition", "kesanso", "medobi", "malso", "city"]
    if all(d.get(k) and d.get(k) != "—" for k in required):
        rows.append([InlineKeyboardButton("✅ Отправить", callback_data="send")])

    rows.append([InlineKeyboardButton("🔄 Заново", callback_data="restart")])
    return text, InlineKeyboardMarkup(rows)

async def refresh_form(ctx: ContextTypes.DEFAULT_TYPE):
    text, kb = build_form(ctx.user_data)
    try:
        await ctx.bot.edit_message_text(
            chat_id=ctx.user_data["form_chat"],
            message_id=ctx.user_data["form_msg"],
            text=text,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception:
        pass

# ── Хэндлеры ─────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Отправь ссылку на Энкар.")
    return WAITING_LINK

async def receive_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg_text = (update.message.text or "").strip()
    if "http" not in msg_text:
        await update.message.reply_text("Не вижу ссылку. Попробуй ещё раз.")
        return WAITING_LINK

    ctx.user_data.clear()
    ctx.user_data["url"] = msg_text

    match = re.search(r'/detail/(\d+)', msg_text)
    car_id = match.group(1) if match else None

    wait_msg = await update.message.reply_text("⏳ Загружаю...")
    parsed = await parse_encar_api(car_id) if car_id else {}
    ctx.user_data["name"] = parsed.get("name", "—")
    ctx.user_data["city"] = parsed.get("city", "—")
    await wait_msg.delete()

    text, kb = build_form(ctx.user_data)
    form_msg = await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    ctx.user_data["form_msg"]  = form_msg.message_id
    ctx.user_data["form_chat"] = form_msg.chat_id
    return FILLING

async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    d = query.data

    ctx.user_data["form_msg"]  = query.message.message_id
    ctx.user_data["form_chat"] = query.message.chat_id

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

    # Простые кнопки
    simple = {
        "keys_1": ("keys", "1"),       "keys_2": ("keys", "2"),
        "cond_clean": ("condition", "чистая"),
        "cond_check": ("condition", "надо смотреть"),
        "kes_100": ("kesanso", "100%"), "kes_no": ("kesanso", "нет"),
        "med_440": ("medobi", "440000"), "med_450": ("medobi", "450000"),
        "med_330": ("medobi", "330000"),
        "mal_now": ("malso", "сразу"),  "mal_tomorrow": ("malso", "завтра"),
        "mal_2weeks": ("malso", "1-2 недели"),
    }
    if d in simple:
        key, val_s = simple[d]
        ctx.user_data[key] = val_s
        text, kb = build_form(ctx.user_data)
        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            pass
        return FILLING

    # Текстовый ввод
    prompts = {
        "edit_name":  ("name_input",    "✏️ Введи *марку и модель* (например: KIA K5):"),
        "edit_plate": ("plate_input",   "✏️ Введи *номер авто* (например: 256수7232):"),
        "edit_price": ("price_input",   "✏️ Введи *цену* в вонах (например: 26500000):"),
        "kes_input":  ("kesanso_input", "✏️ Введи сумму кесансо:"),
        "med_input":  ("medobi_input",  "✏️ Введи сумму медоби:"),
        "mal_input":  ("malso_input",   "✏️ Введи дату или срок мальсо:"),
        "edit_city":  ("city_input",    "✏️ Введи *город* (например: Сувон):"),
    }
    if d in prompts:
        field, prompt = prompts[d]
        ctx.user_data["waiting_for"] = field
        await query.message.reply_text(prompt, parse_mode="Markdown")
        return WAITING_TEXT_INPUT

    return FILLING

async def receive_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val_t = (update.message.text or "").strip()
    field = ctx.user_data.get("waiting_for")

    field_map = {
        "name_input":    "name",
        "plate_input":   "plate",
        "price_input":   "price",
        "kesanso_input": "kesanso",
        "medobi_input":  "medobi",
        "malso_input":   "malso",
        "city_input":    "city",
    }
    if field in field_map:
        ctx.user_data[field_map[field]] = val_t
        ctx.user_data["waiting_for"] = None
        await refresh_form(ctx)

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
            FILLING: [
                CallbackQueryHandler(button_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text_input),
            ],
            WAITING_TEXT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text_input),
                CallbackQueryHandler(button_callback),
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
