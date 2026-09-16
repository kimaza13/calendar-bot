import os
import re
import json
import logging
import tempfile
import httpx
import groq
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_API_KEY      = os.environ["GROQ_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_TOKEN_JSON = os.environ["GOOGLE_TOKEN_JSON"]
WEBHOOK_URL       = os.environ.get("WEBHOOK_URL", "")

groq_client = groq.Groq(api_key=GROQ_API_KEY)
conversation_history = {}
MAX_HISTORY = 10

# ═══════════════════════════════════════════════════════════════════════════════
#  CAR-CHECK: состояния ConversationHandler
# ═══════════════════════════════════════════════════════════════════════════════
FILLING, WAITING_TEXT_INPUT = range(2)

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

# ── Car-check: форматирование ─────────────────────────────────────────────────
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

def format_car_card(d: dict) -> str:
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

# ── Car-check: форма с кнопками ───────────────────────────────────────────────
def fval(d, key, fmt=False):
    v = d.get(key)
    if not v or v == "—":
        return "—"
    return fmt_money(v) if fmt else v

def dot(d, key, target):
    return " ✅" if d.get(key) == target else ""

def build_car_form(d: dict):
    text = (
        f"🚗 *Марка и модель:* {fval(d,'name')}\n"
        f"🔢 *Номер:* `{fval(d,'plate')}`\n"
        f"💵 *Цена:* `{fmt_money(fval(d,'price'))}`\n"
        f"🔑 *Ключи:* {fval(d,'keys')}\n"
        f"🚘 *Состояние:* {fval(d,'condition')}\n"
        f"📋 *Кесансо:* {fmt_money(fval(d,'kesanso'))}\n"
        f"💰 *Медоби:* {fmt_money(fval(d,'medobi'))}\n"
        f"📅 *Мальсо:* {fval(d,'malso')}\n"
        f"📍 *Город:* {fval(d,'city')}"
    )

    rows = [
        [InlineKeyboardButton(
            f"🚗 Марка и модель{' ✅' if d.get('name') and d.get('name') != '—' else ' ✏️'}",
            callback_data="cc_edit_name")],
        [InlineKeyboardButton(
            f"🔢 Номер авто{' ✅' if d.get('plate') else ' ✏️'}",
            callback_data="cc_edit_plate")],
        [InlineKeyboardButton(
            f"💵 Цена{' ✅' if d.get('price') else ' ✏️'}",
            callback_data="cc_edit_price")],
        [
            InlineKeyboardButton(f"🔑 1{dot(d,'keys','1')}", callback_data="cc_keys_1"),
            InlineKeyboardButton(f"🔑 2{dot(d,'keys','2')}", callback_data="cc_keys_2"),
        ],
        [
            InlineKeyboardButton(f"✅ Чистая{dot(d,'condition','чистая')}", callback_data="cc_cond_clean"),
            InlineKeyboardButton(f"🔍 Надо смотреть{dot(d,'condition','надо смотреть')}", callback_data="cc_cond_check"),
        ],
        [
            InlineKeyboardButton(f"100%{dot(d,'kesanso','100%')}", callback_data="cc_kes_100"),
            InlineKeyboardButton(f"Нет{dot(d,'kesanso','нет')}", callback_data="cc_kes_no"),
            InlineKeyboardButton("Ввести сумму", callback_data="cc_kes_input"),
        ],
        [
            InlineKeyboardButton(f"440,000{dot(d,'medobi','440000')}", callback_data="cc_med_440"),
            InlineKeyboardButton(f"450,000{dot(d,'medobi','450000')}", callback_data="cc_med_450"),
            InlineKeyboardButton(f"330,000{dot(d,'medobi','330000')}", callback_data="cc_med_330"),
            InlineKeyboardButton("Другое", callback_data="cc_med_input"),
        ],
        [
            InlineKeyboardButton(f"Сразу{dot(d,'malso','сразу')}", callback_data="cc_mal_now"),
            InlineKeyboardButton(f"Завтра{dot(d,'malso','завтра')}", callback_data="cc_mal_tomorrow"),
            InlineKeyboardButton(f"1-2 нед{dot(d,'malso','1-2 недели')}", callback_data="cc_mal_2weeks"),
            InlineKeyboardButton("Другое", callback_data="cc_mal_input"),
        ],
        [InlineKeyboardButton(
            f"📍 Город{' ✅' if d.get('city') and d.get('city') != '—' else ' ✏️'}",
            callback_data="cc_edit_city")],
    ]

    required = ["name", "plate", "price", "keys", "condition", "kesanso", "medobi", "malso", "city"]
    if all(d.get(k) and d.get(k) != "—" for k in required):
        rows.append([InlineKeyboardButton("✅ Отправить", callback_data="cc_send")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cc_cancel")])

    return text, InlineKeyboardMarkup(rows)

async def refresh_car_form(ctx: ContextTypes.DEFAULT_TYPE):
    text, kb = build_car_form(ctx.user_data.get("cc", {}))
    try:
        await ctx.bot.edit_message_text(
            chat_id=ctx.user_data["cc_chat"],
            message_id=ctx.user_data["cc_msg"],
            text=text,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════════════════
#  ASSISTANT: вспомогательные функции
# ═══════════════════════════════════════════════════════════════════════════════
async def get_exchange_rates() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://open.er-api.com/v6/latest/USD")
            data = resp.json()
            usd_to_krw = data["rates"]["KRW"]
            usd_to_rub = data["rates"]["RUB"]
            usd_to_eur = 1 / data["rates"]["EUR"]
            return {"usd_krw": usd_to_krw, "usd_rub": usd_to_rub, "eur_rub": usd_to_eur * usd_to_rub}
    except Exception:
        return {"usd_krw": 1350, "usd_rub": 1380, "eur_rub": 1500}

SYSTEM_PROMPT = """Ты умный универсальный ассистент. Умеешь отвечать на любые вопросы, а также специализируешься на экспорте автомобилей из Кореи в СНГ.
Анализируй запрос и отвечай ТОЛЬКО валидным JSON без markdown.

=== 1. КАЛЬКУЛЯТОР ИМПОРТА в Россию (физлицо) ===
Курсы: $1=1380р, $1=1350 вон, 1 евро=1500р

ТАМОЖНЯ (физлицо, ЕТС):
Берётся МАКСИМУМ из двух значений: процентная ставка И минимальная ставка за см³.

До 3 лет:
- до 8500 евро: макс(54% от цены_евро, 2.5€×см³)
- 8500-16700 евро: макс(48% от цены_евро, 3.5€×см³)
- свыше 16700 евро: макс(48% от цены_евро, 5.5€×см³)

3-5 лет: макс(48% от цены_евро, 3.5€×см³)
5-7 лет: макс(48% от цены_евро, 3.5€×см³)
старше 7 лет (зависит от объёма):
- до 1000см³: макс(48% от цены_евро, 1.4€×см³)
- 1000-1500см³: макс(48% от цены_евро, 1.5€×см³)
- 1500-1800см³: макс(48% от цены_евро, 1.7€×см³)
- 1800-2300см³: макс(48% от цены_евро, 2.5€×см³)
- 2300-3000см³: макс(48% от цены_евро, 2.7€×см³)
- свыше 3000см³: макс(48% от цены_евро, 3.0€×см³)

Плюс таможенное оформление: 4924₽ (фиксировано)

УТИЛЬСБОР (физлицо, первая машина):
до 3 лет: 20000 × коэффициент
- до 1000см³: 20000 × 0.26 = 5200₽
- 1000-2000см³: 20000 × 2.74 = 54800₽
- свыше 2000см³: 20000 × 5.63 = 112600₽

3-5 лет: 20000 × коэффициент
- до 1000см³: 20000 × 0.26 = 5200₽
- 1000-2000см³: 20000 × 2.74 = 54800₽
- свыше 2000см³: 20000 × 5.63 = 112600₽

старше 5 лет: 20000 × коэффициент
- до 1000см³: 20000 × 0.26 = 5200₽
- 1000-2000см³: 20000 × 5.63 = 112600₽
- свыше 2000см³: 20000 × 8.45 = 169000₽

Фиксированные: брокер 25000р + логистика 150000р + услуги 100000р = 275000р
Итого = цена_руб + таможня + утилсбор + 275000

Формат ответа:
{"intent":"calc","reply":"итог текстом","data":{"car":"название","price_krw":число,"price_rub":число,"price_eur":число,"customs_rub":число,"util_rub":число,"broker_rub":25000,"logistics_rub":150000,"service_rub":100000,"total_rub":число,"usd_krw":число,"usd_rub":число,"eur_rub":число}}

Если запрос содержит цену авто И расходы по Корее (фрахт) — используй intent "full_calc":
{"intent":"full_calc","reply":"итог","data":{"car":"название","year":число,"age":"new|3-5|5-7|7+","engine_cc":число,"engine_type":"бензин|дизель|гибрид|электро","price_krw":число,"korea_expenses_krw":число,"total_krw":число,"price_usd":число,"price_rub":число,"customs_rub":число,"util_rub":число,"delivery_msk_rub":число,"usd_krw":число,"usd_rub":число,"eur_rub":число}}
ВАЖНО: delivery_msk_rub = 0 если пользователь не назвал сумму доставки до Москвы явно.

Если не хватает данных для full_calc (нет объёма или возраста) — используй intent "clarify".

=== 2. КАРТОЧКА ДИЛЕРА ===
Когда называют цену авто, медоби, торг и залог — считай остаток дилеру.
Формула: остаток_база = цена - залог - торг, итого = остаток_база + медоби
{"intent":"dealer","reply":"карточка готова","data":{"car":"название если есть","price_krw":число,"medobi_krw":число,"torg_krw":число,"zalog_krw":число}}

=== 3. КАЛЕНДАРЬ ===
Сегодня: {today}, день недели: {weekday}.
{"intent":"calendar","reply":"подтверждение","data":{"title":"название","date":"YYYY-MM-DD","time":"HH:MM","duration_hours":1}}

=== 4. УТОЧНЕНИЕ ===
{"intent":"clarify","reply":"какой вопрос задать"}

=== 5. ЧАТ ===
{"intent":"chat","reply":"ответ"}

=== 6. ПЕРЕВОДЧИК ===
{"intent":"translate","reply":"","data":{"text":"что переводить","target_lang":"korean|russian|english|uzbek"}}"""

def get_calendar_service():
    token_data = json.loads(GOOGLE_TOKEN_JSON)
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes", ["https://www.googleapis.com/auth/calendar"]),
    )
    return build("calendar", "v3", credentials=creds)

async def transcribe_voice(file_path: str) -> str:
    with open(file_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            file=("voice.ogg", f),
            model="whisper-large-v3",
            language="ru",
        )
    return result.text.strip()

def calculate_customs(price_krw, engine_cc, age, engine_type, rates) -> dict:
    usd_krw = rates["usd_krw"]
    usd_rub = rates["usd_rub"]
    eur_rub = rates["eur_rub"]
    price_usd = price_krw / usd_krw
    price_eur = price_usd / 1.09

    if age == "new":
        rate_eur = 2.5 if price_eur <= 8500 else (3.5 if price_eur <= 16700 else 5.5)
    elif age in ["3-5", "5-7"]:
        rate_eur = 2.5
    else:
        if engine_cc <= 1000: rate_eur = 1.4
        elif engine_cc <= 1500: rate_eur = 1.5
        elif engine_cc <= 1800: rate_eur = 1.7
        elif engine_cc <= 2300: rate_eur = 2.5
        elif engine_cc <= 3000: rate_eur = 2.7
        else: rate_eur = 3.0

    customs = round(rate_eur * engine_cc * eur_rub + 4924)
    util = 5200
    return {
        "customs_rub": customs, "util_rub": util,
        "price_usd": round(price_usd),
        "price_rub": round(price_usd * usd_rub),
        "price_eur": round(price_eur),
    }

async def ask_claude(user_message: str, chat_id: int) -> dict:
    now = datetime.now()
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    system = SYSTEM_PROMPT.replace("{today}", now.strftime("%d.%m.%Y")).replace("{weekday}", weekdays[now.weekday()])

    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
    conversation_history[chat_id].append({"role": "user", "content": user_message})
    if len(conversation_history[chat_id]) > MAX_HISTORY * 2:
        conversation_history[chat_id] = conversation_history[chat_id][-MAX_HISTORY * 2:]

    rates = await get_exchange_rates()
    system += f"\n\nАКТУАЛЬНЫЕ КУРСЫ: $1={rates['usd_krw']:.0f}₩, $1={rates['usd_rub']:.2f}₽, €1={rates['eur_rub']:.2f}₽"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "system": system,
                "messages": conversation_history[chat_id],
            },
        )
        data = resp.json()
        if "error" in data:
            raise Exception(f"API error: {data['error']}")
        raw = data["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
        conversation_history[chat_id].append({"role": "assistant", "content": raw})
        return parsed

def create_calendar_event(title, date, time, duration_hours=1) -> str:
    service = get_calendar_service()
    start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(hours=duration_hours)
    event = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Seoul"},
        "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "Asia/Seoul"},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}]},
    }
    result = service.events().insert(calendarId="primary", body=event).execute()
    return result.get("htmlLink", "")

def fmt(n):
    return f"{int(n):,}".replace(",", " ")

def format_calc_result(data: dict) -> str:
    return "\n".join([
        f"🚗 *{data.get('car','Авто')}*", "",
        f"📊 *Курсы:* $1={data.get('usd_krw',1350):.0f}₩ | $1={data.get('usd_rub',1380):.2f}₽ | €1={data.get('eur_rub',1500):.2f}₽", "",
        f"💰 Цена: {fmt(data.get('price_krw',0))}₩ → {fmt(data.get('price_rub',0))}₽",
        f"🛃 Таможня: {fmt(data.get('customs_rub',0))}₽",
        f"♻️ Утильсбор: {fmt(data.get('util_rub',0))}₽",
        f"📋 Брокер: 25 000₽",
        f"🚢 Логистика: 150 000₽",
        f"🏢 Услуги: 100 000₽", "",
        f"✅ *Итого: {fmt(data.get('total_rub',0))}₽*",
    ])

def format_full_calc(data: dict) -> str:
    price_krw  = data.get("price_krw", 0)
    korea_exp  = data.get("korea_expenses_krw", 0)
    total_krw  = price_krw + korea_exp
    usd_krw    = data.get("usd_krw", 1350)
    usd_rub    = data.get("usd_rub", 1380)
    eur_rub    = data.get("eur_rub", 1500)
    total_usd  = round(total_krw / usd_krw)
    total_rub  = round(total_usd * usd_rub)
    customs    = data.get("customs_rub", 0)
    util       = data.get("util_rub", 0)
    broker     = 110000
    contract   = 100000
    delivery   = data.get("delivery_msk_rub", 0)
    total_vldk = total_rub + customs + util + broker + contract
    total_msk  = total_vldk + delivery
    lines = [
        f"🚗 *{data.get('car','Авто')}*", "",
        f"📊 $1={usd_krw:.0f}₩ | $1={usd_rub:.2f}₽ | €1={eur_rub:.2f}₽", "",
        f"🇰🇷 *Корея*",
        f"Цена: {fmt(price_krw)}₩",
        f"Расходы+фрахт: {fmt(korea_exp)}₩",
        f"Итого KRW: {fmt(total_krw)}₩ → ${fmt(total_usd)} → {fmt(total_rub)}₽", "",
        f"🇷🇺 *Россия*",
        f"Таможня: {fmt(customs)}₽",
        f"Утильсбор: {fmt(util)}₽",
        f"Брокер: {fmt(broker)}₽",
        f"Договор: {fmt(contract)}₽", "",
        f"📦 *Total ВДК: {fmt(total_vldk)}₽*",
    ]
    if delivery > 0:
        lines += [f"🚛 Доставка→МСК: {fmt(delivery)}₽", f"🏁 *Total МСК: {fmt(total_msk)}₽*"]
    return "\n".join(lines)

def format_dealer_card(data: dict) -> str:
    price    = data["price_krw"]
    medobi   = data["medobi_krw"]
    torg     = data["torg_krw"]
    zalog    = data["zalog_krw"]
    ostatok  = price - zalog - torg
    total    = ostatok + medobi
    return "\n".join([
        f"💵 *Расчёт с дилером*", "",
        f"Цена: {fmt(price)}₩",
        f"Медоби: {fmt(medobi)}₩",
        f"Торг: {fmt(torg)}₩",
        f"Залог: {fmt(zalog)}₩", "",
        f"*Остаток: {fmt(ostatok)} + {fmt(medobi)} = {fmt(total)}₩*",
    ])

async def process_assistant_message(update: Update, text: str):
    try:
        result = await ask_claude(text, update.message.chat_id)
        intent = result.get("intent")
        reply  = result.get("reply", "")
        data   = result.get("data", {})

        if intent == "calc":
            rates = await get_exchange_rates()
            calc  = calculate_customs(data.get("price_krw",0), data.get("engine_cc",1600), data.get("age","3-5"), data.get("engine_type","бензин"), rates)
            data.update(calc)
            data.update({"usd_krw": rates["usd_krw"], "usd_rub": rates["usd_rub"], "eur_rub": rates["eur_rub"]})
            await update.message.reply_text(format_calc_result(data), parse_mode="Markdown")

        elif intent == "full_calc":
            rates = await get_exchange_rates()
            calc  = calculate_customs(data.get("total_krw", data.get("price_krw",0)), data.get("engine_cc",1600), data.get("age","3-5"), data.get("engine_type","бензин"), rates)
            data.update(calc)
            data.update({"usd_krw": rates["usd_krw"], "usd_rub": rates["usd_rub"], "eur_rub": rates["eur_rub"]})
            await update.message.reply_text(format_full_calc(data), parse_mode="Markdown")

        elif intent == "dealer":
            await update.message.reply_text(format_dealer_card(data), parse_mode="Markdown")

        elif intent == "calendar":
            try:
                create_calendar_event(data["title"], data["date"], data["time"], data.get("duration_hours", 1))
                now = datetime.now()
                weekdays = ["пн","вт","ср","чт","пт","сб","вс"]
                dt = datetime.strptime(f"{data['date']} {data['time']}", "%Y-%m-%d %H:%M")
                date_fmt = f"{dt.strftime('%d.%m.%Y')} ({weekdays[dt.weekday()]})"
                await update.message.reply_text(f"📅 *{data['title']}*\n🕐 {date_fmt} в {data['time']}\n\n✅ Добавлено в календарь", parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка календаря: {e}")

        elif intent == "translate":
            lang_prompts = {
                "korean": "корейский язык. Используй естественный стиль как носитель. Уровень вежливости 해요체 для нейтрального, 합쇼체 для делового.",
                "russian": "русский язык. Переводи естественно.",
                "english": "английский язык. Переводи естественно.",
                "uzbek": "узбекский язык. Переводи естественно.",
            }
            target = data.get("target_lang", "korean")
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 1024,
                        "system": "Ты профессиональный переводчик. Только перевод, без пояснений.",
                        "messages": [{"role": "user", "content": f"Переведи на {lang_prompts.get(target, target)}:\n\n{data.get('text','')}"}],
                    },
                )
                translated = resp.json()["content"][0]["text"].strip()
            flags = {"korean": "🇰🇷", "russian": "🇷🇺", "english": "🇺🇸", "uzbek": "🇺🇿"}
            await update.message.reply_text(f"{flags.get(target,'🌐')} {translated}")

        elif intent == "clarify":
            await update.message.reply_text(f"🤔 {reply}")

        else:
            await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"Assistant error: {e}")
        await update.message.reply_text("❌ Что-то пошло не так. Попробуй ещё раз.")

# ═══════════════════════════════════════════════════════════════════════════════
#  HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой ассистент.\n\n"
        "🚗 Отправь ссылку Энкар → заполним карточку авто\n"
        "💰 Спроси расчёт таможни или стоимости авто\n"
        "📅 Добавлю встречу в календарь\n"
        "🌐 Переведу текст\n"
        "💬 Отвечу на любой вопрос"
    )

async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id in conversation_history:
        conversation_history[chat_id] = []
    await update.message.reply_text("🔄 История диалога очищена")

# ── Car-check: запуск формы при получении ссылки Энкар ───────────────────────
async def handle_encar_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url = (update.message.text or "").strip()
    ctx.user_data["cc"] = {"url": url}

    match = re.search(r'/detail/(\d+)', url)
    car_id = match.group(1) if match else None

    wait_msg = await update.message.reply_text("⏳ Загружаю данные авто...")
    parsed = await parse_encar_api(car_id) if car_id else {}
    ctx.user_data["cc"]["name"] = parsed.get("name", "—")
    ctx.user_data["cc"]["city"] = parsed.get("city", "—")
    await wait_msg.delete()

    text, kb = build_car_form(ctx.user_data["cc"])
    form_msg = await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    ctx.user_data["cc_msg"]  = form_msg.message_id
    ctx.user_data["cc_chat"] = form_msg.chat_id
    return FILLING

# ── Car-check: кнопки ────────────────────────────────────────────────────────
async def car_button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    d_key = query.data

    ctx.user_data["cc_msg"]  = query.message.message_id
    ctx.user_data["cc_chat"] = query.message.chat_id
    cc = ctx.user_data.setdefault("cc", {})

    if d_key == "cc_cancel":
        ctx.user_data.pop("cc", None)
        await query.message.edit_text("❌ Отменено.")
        return ConversationHandler.END

    if d_key == "cc_send":
        card = format_car_card(cc)
        await query.message.reply_text(card)
        ctx.user_data.pop("cc", None)
        await query.message.reply_text("✅ Готово! Можешь отправить новую ссылку или задать вопрос.")
        return ConversationHandler.END

    simple = {
        "cc_keys_1": ("keys", "1"),      "cc_keys_2": ("keys", "2"),
        "cc_cond_clean": ("condition", "чистая"),
        "cc_cond_check": ("condition", "надо смотреть"),
        "cc_kes_100": ("kesanso", "100%"), "cc_kes_no": ("kesanso", "нет"),
        "cc_med_440": ("medobi", "440000"), "cc_med_450": ("medobi", "450000"),
        "cc_med_330": ("medobi", "330000"),
        "cc_mal_now": ("malso", "сразу"),  "cc_mal_tomorrow": ("malso", "завтра"),
        "cc_mal_2weeks": ("malso", "1-2 недели"),
    }
    if d_key in simple:
        key, val = simple[d_key]
        cc[key] = val
        text, kb = build_car_form(cc)
        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            pass
        return FILLING

    prompts = {
        "cc_edit_name":  ("cc_name_input",    "✏️ Введи *марку и модель* (например: KIA K5):"),
        "cc_edit_plate": ("cc_plate_input",   "✏️ Введи *номер авто* (например: 256수7232):"),
        "cc_edit_price": ("cc_price_input",   "✏️ Введи *цену* в вонах (например: 26500000):"),
        "cc_kes_input":  ("cc_kesanso_input", "✏️ Введи сумму кесансо:"),
        "cc_med_input":  ("cc_medobi_input",  "✏️ Введи сумму медоби:"),
        "cc_mal_input":  ("cc_malso_input",   "✏️ Введи дату или срок мальсо:"),
        "cc_edit_city":  ("cc_city_input",    "✏️ Введи *город* (например: Сувон):"),
    }
    if d_key in prompts:
        field, prompt = prompts[d_key]
        ctx.user_data["cc_waiting"] = field
        await query.message.reply_text(prompt, parse_mode="Markdown")
        return WAITING_TEXT_INPUT

    return FILLING

# ── Car-check: текстовый ввод ─────────────────────────────────────────────────
async def car_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val   = (update.message.text or "").strip()
    field = ctx.user_data.get("cc_waiting")
    cc    = ctx.user_data.setdefault("cc", {})

    field_map = {
        "cc_name_input":    "name",
        "cc_plate_input":   "plate",
        "cc_price_input":   "price",
        "cc_kesanso_input": "kesanso",
        "cc_medobi_input":  "medobi",
        "cc_malso_input":   "malso",
        "cc_city_input":    "city",
    }
    if field in field_map:
        cc[field_map[field]] = val
        ctx.user_data["cc_waiting"] = None
        await refresh_car_form(ctx)

    return FILLING

# ── Assistant: текст и голос ──────────────────────────────────────────────────
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    await process_assistant_message(update, update.message.text)

async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    voice = update.message.voice
    file  = await ctx.bot.get_file(voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        text = await transcribe_voice(tmp.name)
    await update.message.reply_text(f"🎤 _{text}_", parse_mode="Markdown")
    await process_assistant_message(update, text)

# ═══════════════════════════════════════════════════════════════════════════════
#  ЗАПУСК
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Car-check conversation
    car_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & filters.Regex(r"encar\.com"), handle_encar_link),
        ],
        states={
            FILLING: [
                CallbackQueryHandler(car_button_callback, pattern="^cc_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, car_text_input),
            ],
            WAITING_TEXT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, car_text_input),
                CallbackQueryHandler(car_button_callback, pattern="^cc_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_user=True,
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(car_conv)
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if WEBHOOK_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8000)),
            webhook_url=f"{WEBHOOK_URL}/webhook",
            url_path="/webhook",
        )
    else:
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
