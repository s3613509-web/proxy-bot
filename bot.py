import asyncio, logging, hashlib, random, string, os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import *
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web
import sqlite3

TOKEN = "8623163395:AAEWna0-DmFKdFvCO8z6NWeRcA-ybnR55Ss"
ADMIN_IDS = [8504186560]
BOT_USERNAME = "FrpPortSaller_bot"
HEALTH_CHECK_PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bot = Bot(token=TOKEN)
dp = Dispatcher()
conn = sqlite3.connect('standoff.db', check_same_thread=False)
c = conn.cursor()

c.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0,
        banned INTEGER DEFAULT 0, total_spent REAL DEFAULT 0,
        registered TEXT, ref_code TEXT, discount INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS cheats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, features TEXT, version TEXT,
        price_day REAL, price_week REAL, price_month REAL, price_forever REAL,
        status TEXT DEFAULT 'active'
    );
    CREATE TABLE IF NOT EXISTS keys_pool (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE, cheat_id INTEGER, duration INTEGER,
        status TEXT DEFAULT 'free', created TEXT,
        sold_to INTEGER, sold_date TEXT, expiry TEXT
    );
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, cheat_id INTEGER, amount REAL,
        currency TEXT, status TEXT, date TEXT, payload TEXT
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER, referred_id INTEGER,
        amount REAL DEFAULT 20, date TEXT
    );
    CREATE TABLE IF NOT EXISTS promocodes (
        code TEXT PRIMARY KEY, discount INTEGER, uses INTEGER, max_uses INTEGER
    );
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, message TEXT,
        reply TEXT, status TEXT DEFAULT 'open', created TEXT
    );
''')
conn.commit()

c.execute("SELECT COUNT(*) FROM cheats")
if c.fetchone()[0] == 0:
    for name, feat, v, pd, pw, pm, pf in [
        ("🎯 AIM BOT", "Aim Lock,Silent Aim,FOV,Smooth,Priority", "v3.2", 150, 500, 1500, 5000),
        ("👁 WALLHACK", "ESP Box,ESP HP,ESP Dist,ESP Name,Chams", "v3.2", 100, 350, 1000, 3500),
        ("📡 RADAR HACK", "Radar 2D,Direction,Range,Filter", "v3.2", 80, 250, 800, 2500),
        ("🔫 NO RECOIL", "Zero Recoil,Spread,Burst,Custom", "v3.2", 100, 300, 1000, 3000),
        ("👑 FULL PACK", "AIM+WH+RADAR+RECOIL,Spoofer,Bypass,VIP", "v3.2", 350, 1200, 3500, 12000)
    ]:
        c.execute("INSERT INTO cheats (name,features,version,price_day,price_week,price_month,price_forever) VALUES (?,?,?,?,?,?,?)",
                  (name, feat, v, pd, pw, pm, pf))
    conn.commit()

DURATIONS = {1: "1 день", 7: "1 неделя", 30: "1 месяц", 365: "Навсегда"}
DURATIONS_PRICE_INDEX = {1: 3, 7: 4, 30: 5, 365: 6}

class AdminStates(StatesGroup):
    waiting_mass_text = State()
    waiting_promo_discount = State()
    waiting_promo_uses = State()
    waiting_ticket_reply = State()
    waiting_add_balance_user = State()
    waiting_add_balance_amount = State()
    waiting_gen_cheat = State()
    waiting_gen_count = State()

class UserStates(StatesGroup):
    waiting_ticket_text = State()
    waiting_promo_input = State()

def gen_key():
    return '-'.join(''.join(random.choices(string.ascii_uppercase + string.digits, k=4)) for _ in range(4))

def main_menu():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🎮 КАТАЛОГ ЧИТОВ", callback_data="catalog"))
    b.row(InlineKeyboardButton(text="🔑 Мои ключи", callback_data="my_keys"))
    b.row(InlineKeyboardButton(text="🛡 Гарантия / Замена", callback_data="warranty"))
    b.row(InlineKeyboardButton(text="📥 Инструкция", callback_data="setup"))
    b.row(InlineKeyboardButton(text="👤 Профиль", callback_data="profile"))
    b.row(InlineKeyboardButton(text="💰 Пополнить", callback_data="topup"))
    b.row(InlineKeyboardButton(text="👥 Рефералы", callback_data="ref_menu"))
    b.row(InlineKeyboardButton(text="🎟 Промокод", callback_data="promo_enter"))
    b.row(InlineKeyboardButton(text="📞 Поддержка", callback_data="support_menu"))
    return b.as_markup()

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🔑 Создать ключи")],
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🎟 Промокод")],
        [KeyboardButton(text="➕ Баланс"), KeyboardButton(text="📋 Тикеты")],
        [KeyboardButton(text="🔙 Выход")],
    ], resize_keyboard=True)

# СТАРТ
@dp.message(Command("start"))
async def start(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    c.execute("SELECT id, banned FROM users WHERE id=?", (uid,))
    u = c.fetchone()
    if u and u[1] == 1:
        await msg.answer("❌ Заблокированы."); return
    if not u:
        ref_code = hashlib.md5(str(uid).encode()).hexdigest()[:10]
        c.execute("INSERT INTO users (id, username, balance, registered, ref_code) VALUES (?, ?, 10, ?, ?)",
                  (uid, msg.from_user.username, datetime.now().isoformat(), ref_code))
        conn.commit()
        args = msg.text.split()
        if len(args) > 1 and args[1].startswith("ref_"):
            c.execute("SELECT id FROM users WHERE ref_code=? AND id!=?", (args[1][4:], uid))
            if r := c.fetchone():
                c.execute("INSERT INTO referrals (referrer_id, referred_id, date) VALUES (?, ?, ?)",
                          (r[0], uid, datetime.now().isoformat()))
                c.execute("UPDATE users SET balance=balance+20 WHERE id=?", (r[0],))
                conn.commit()
    await msg.answer(
        "🎮 *STANDOFF 2 CHEATS*\n\n"
        "🔥 Премиум читы\n🎯 AIM | 👁 WH | 📡 RADAR | 🔫 RECOIL | 👑 FULL PACK\n\n"
        "💎 Оплата: Telegram Stars\n🎁 Пробный период: 1 час\n🛡 Гарантия замены при бане\n\n"
        "💰 Бонус: 10₽ на баланс!",
        parse_mode="Markdown", reply_markup=main_menu()
    )

@dp.message(Command("setup"))
async def cmd_setup(msg: Message):
    await msg.answer(
        "📥 *Инструкция по установке:*\n\n"
        "1. Скачайте инжектор (ссылка в личном кабинете)\n"
        "2. Установите APK\n"
        "3. Запустите Standoff 2\n"
        "4. В инжекторе введите полученный ключ\n"
        "5. Настройте функции под себя\n\n"
        "⚠️ *Важно:* Используйте на втором аккаунте!",
        parse_mode="Markdown"
    )

# КАТАЛОГ
@dp.callback_query(F.data == "catalog")
async def catalog(cb: types.CallbackQuery):
    c.execute("SELECT id, name, price_day FROM cheats WHERE status='active'")
    b = InlineKeyboardBuilder()
    for cid, name, price in c.fetchall():
        b.row(InlineKeyboardButton(text=f"{name} — от {price}₽", callback_data=f"cheat_{cid}"))
    b.row(InlineKeyboardButton(text="🔙 Меню", callback_data="start_menu"))
    await cb.message.edit_text("🎮 *КАТАЛОГ ЧИТОВ*\nВыберите чит:", parse_mode="Markdown", reply_markup=b.as_markup())

@dp.callback_query(F.data == "start_menu")
async def start_menu(cb: types.CallbackQuery):
    await cb.message.edit_text("🎮 *STANDOFF 2 CHEATS*", parse_mode="Markdown", reply_markup=main_menu())

@dp.callback_query(F.data.startswith("cheat_"))
async def cheat_detail(cb: types.CallbackQuery):
    cid = int(cb.data.split("_")[1])
    c.execute("SELECT * FROM cheats WHERE id=?", (cid,))
    ch = c.fetchone()
    if not ch:
        await cb.answer("Чит не найден"); return
    
    b = InlineKeyboardBuilder()
    prices = [(1, ch[3]), (7, ch[4]), (30, ch[5]), (365, ch[6])]
    for days, price in prices:
        b.row(InlineKeyboardButton(text=f"{DURATIONS[days]} — {price}₽", callback_data=f"buy_{cid}_{days}"))
    b.row(InlineKeyboardButton(text="🎁 Пробный час (бесплатно)", callback_data=f"trial_{cid}"))
    b.row(InlineKeyboardButton(text="🔙 Каталог", callback_data="catalog"))
    
    features = '\n'.join([f"• {f}" for f in ch[2].split(',')])
    await cb.message.edit_text(
        f"{ch[1]}\n\n⚙ *Функции:*\n{features}\n\n🔄 Версия: {ch[7]}\n\n📅 Выберите срок:",
        parse_mode="Markdown", reply_markup=b.as_markup()
    )

# ПОКУПКА
@dp.callback_query(F.data.startswith("buy_"))
async def buy_cheat(cb: types.CallbackQuery):
    _, cid, days = cb.data.split("_")
    cid, days = int(cid), int(days)
    c.execute("SELECT * FROM cheats WHERE id=?", (cid,))
    ch = c.fetchone()
    price = [ch[3], ch[4], ch[5], ch[6]][[1, 7, 30, 365].index(days)]
    
    await cb.message.answer_invoice(
        title=ch[1],
        description=f"{DURATIONS[days]} | Standoff 2",
        payload=f"cheat_{cid}_{days}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=DURATIONS[days], amount=price)],
        need_name=False, need_phone_number=False, need_email=False,
    )
    await cb.message.edit_text("✅ Счёт на оплату выставлен", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Меню", callback_data="start_menu")]
    ]))

@dp.callback_query(F.data.startswith("trial_"))
async def trial_cheat(cb: types.CallbackQuery):
    cid = int(cb.data.split("_")[1])
    
    # Проверка на повторный пробный
    c.execute("SELECT id FROM payments WHERE user_id=? AND payload LIKE '%trial%'", (cb.from_user.id,))
    if c.fetchone():
        await cb.answer("❌ Вы уже использовали пробный период!", show_alert=True)
        return
    
    key = gen_key()
    expiry = datetime.now() + timedelta(hours=1)
    c.execute("INSERT INTO keys_pool (key, cheat_id, duration, status, created, sold_to, sold_date, expiry) VALUES (?, ?, 0, 'sold', ?, ?, ?, ?)",
              (key, cid, datetime.now().isoformat(), cb.from_user.id, datetime.now().isoformat(), expiry.isoformat()))
    c.execute("INSERT INTO payments (user_id, cheat_id, amount, currency, status, date, payload) VALUES (?, ?, 0, 'FREE', 'success', ?, ?)",
              (cb.from_user.id, cid, datetime.now().isoformat(), f"cheat_{cid}_trial"))
    conn.commit()
    
    c.execute("SELECT name FROM cheats WHERE id=?", (cid,))
    cheat_name = c.fetchone()[0]
    
    await cb.message.edit_text(
        f"🎁 *ПРОБНЫЙ ПЕРИОД АКТИВИРОВАН!*\n\n"
        f"📦 Чит: {cheat_name}\n"
        f"🔑 Ключ: `{key}`\n"
        f"⏰ Длительность: 1 час\n"
        f"📅 До: {expiry.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"📥 Инструкция: /setup",
        parse_mode="Markdown", reply_markup=main_menu()
    )

# ОПЛАТА
@dp.message(F.successful_payment)
async def on_payment(msg: Message):
    payload = msg.successful_payment.invoice_payload
    _, cid, days = payload.split("_")
    cid, days = int(cid), int(days)
    
    # Ищем свободный ключ или создаём новый
    c.execute("SELECT * FROM keys_pool WHERE status='free' AND cheat_id=? AND duration=? LIMIT 1", (cid, days))
    key = c.fetchone()
    
    if key:
        c.execute("UPDATE keys_pool SET status='sold', sold_to=?, sold_date=?, expiry=? WHERE id=?",
                  (msg.from_user.id, datetime.now().isoformat(), (datetime.now() + timedelta(hours=DURATIONS[days] * 24 if days != 365 else 87600)).isoformat(), key[0]))
        key_str = key[1]
    else:
        key_str = gen_key()
        c.execute("INSERT INTO keys_pool (key, cheat_id, duration, status, created, sold_to, sold_date, expiry) VALUES (?, ?, ?, 'sold', ?, ?, ?, ?)",
                  (key_str, cid, days, datetime.now().isoformat(), msg.from_user.id, datetime.now().isoformat(),
                   (datetime.now() + timedelta(hours=DURATIONS[days] * 24 if days != 365 else 87600)).isoformat()))
    
    c.execute("INSERT INTO payments (user_id, cheat_id, amount, currency, status, date, payload) VALUES (?, ?, ?, 'XTR', 'success', ?, ?)",
              (msg.from_user.id, cid, msg.successful_payment.total_amount, datetime.now().isoformat(), payload))
    c.execute("UPDATE users SET total_spent=total_spent+? WHERE id=?", (msg.successful_payment.total_amount, msg.from_user.id))
    conn.commit()
    
    c.execute("SELECT name FROM cheats WHERE id=?", (cid,))
    cheat_name = c.fetchone()[0]
    
    await msg.answer(
        f"✅ *ОПЛАТА ПРОШЛА! ЧИТ АКТИВИРОВАН!*\n\n"
        f"📦 {cheat_name}\n"
        f"🔑 Ключ: `{key_str}`\n"
        f"📅 Срок: {DURATIONS[days]}\n\n"
        f"📥 Инструкция: /setup\n"
        f"🛡 Гарантия замены при бане",
        parse_mode="Markdown", reply_markup=main_menu()
    )

# МОИ КЛЮЧИ
@dp.callback_query(F.data == "my_keys")
async def my_keys(cb: types.CallbackQuery):
    c.execute("SELECT k.key, c.name, k.expiry FROM keys_pool k JOIN cheats c ON k.cheat_id=c.id WHERE k.sold_to=? AND k.status='sold' ORDER BY k.sold_date DESC", (cb.from_user.id,))
    keys = c.fetchall()
    
    if not keys:
        await cb.message.edit_text("🔑 У вас нет активных ключей.\n\n🎁 Доступен пробный период — 1 час бесплатно!", reply_markup=main_menu())
        return
    
    txt = "🔑 *ВАШИ КЛЮЧИ:*\n\n"
    for k in keys:
        try:
            exp = datetime.fromisoformat(k[2])
            now = datetime.now()
            if exp > now:
                left = f"{(exp - now).days} дн. {(exp - now).seconds // 3600} ч."
                status = "🟢 Активен"
            else:
                left = "Истёк"
                status = "🔴 Истёк"
        except:
            left = "?"
            status = "⚪"
        txt += f"{status} *{k[1]}*\n🔑 `{k[0]}`\n⏳ {left}\n\n"
    
    await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=main_menu())

# ГАРАНТИЯ
@dp.callback_query(F.data == "warranty")
async def warranty(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "🛡 *ГАРАНТИЯ ЗАМЕНЫ*\n\n"
        "Если ваш аккаунт заблокировали — мы бесплатно заменим ключ.\n\n"
        "Условия:\n"
        "• Бан должен произойти во время использования нашего чита\n"
        "• Скриншот бана обязателен\n"
        "• Замена 1 раз в период действия ключа\n\n"
        "Для замены — напишите в поддержку.",
        parse_mode="Markdown", reply_markup=main_menu()
    )

# ИНСТРУКЦИЯ
@dp.callback_query(F.data == "setup")
async def setup(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "📥 *ИНСТРУКЦИЯ ПО УСТАНОВКЕ:*\n\n"
        "1. Скачайте инжектор по ссылке из личного кабинета\n"
        "2. Установите APK файл\n"
        "3. Запустите Standoff 2\n"
        "4. В инжекторе введите полученный ключ\n"
        "5. Выберите нужные функции\n"
        "6. Играйте!\n\n"
        "⚠️ *Внимание:*\n"
        "• Используйте на втором аккаунте\n"
        "• Не включайте все функции сразу\n"
        "• При бане — замена бесплатно",
        parse_mode="Markdown", reply_markup=main_menu()
    )

# ПРОФИЛЬ
@dp.callback_query(F.data == "profile")
async def profile(cb: types.CallbackQuery):
    c.execute("SELECT balance, total_spent FROM users WHERE id=?", (cb.from_user.id,))
    u = c.fetchone()
    c.execute("SELECT COUNT(*) FROM payments WHERE user_id=? AND status='success'", (cb.from_user.id,))
    buys = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM keys_pool WHERE sold_to=? AND status='sold'", (cb.from_user.id,))
    active = c.fetchone()[0]
    
    await cb.message.edit_text(
        f"👤 *ПРОФИЛЬ*\n\n"
        f"💰 Баланс: {u[0]}₽\n"
        f"💸 Потрачено: {u[1]}₽\n"
        f"🛒 Покупок: {buys}\n"
        f"🔑 Активных ключей: {active}",
        parse_mode="Markdown", reply_markup=main_menu()
    )

# ПОПОЛНЕНИЕ
@dp.callback_query(F.data == "topup")
async def topup(cb: types.CallbackQuery):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="topup_stars"))
    b.row(InlineKeyboardButton(text="💎 USDT TRC20", callback_data="topup_usdt"))
    b.row(InlineKeyboardButton(text="💳 Карты (скоро)", callback_data="topup_soon"))
    b.row(InlineKeyboardButton(text="🔙 Меню", callback_data="start_menu"))
    await cb.message.edit_text("💰 *ПОПОЛНЕНИЕ БАЛАНСА*\n\nВыберите способ:", parse_mode="Markdown", reply_markup=b.as_markup())

@dp.callback_query(F.data == "topup_soon")
async def topup_soon(cb: types.CallbackQuery):
    await cb.answer("💳 Оплата картами, гривнами, рублями, долларами, евро — в следующем обновлении!", show_alert=True)

# РЕФЕРАЛЫ
@dp.callback_query(F.data == "ref_menu")
async def ref_menu(cb: types.CallbackQuery):
    c.execute("SELECT ref_code FROM users WHERE id=?", (cb.from_user.id,))
    rc = c.fetchone()
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{rc[0]}" if rc else "Ошибка"
    c.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM referrals WHERE referrer_id=?", (cb.from_user.id,))
    cnt, total = c.fetchone()
    
    await cb.message.edit_text(
        f"👥 *РЕФЕРАЛЬНАЯ СИСТЕМА*\n\n"
        f"🔗 Ваша ссылка:\n`{link}`\n\n"
        f"👤 Приглашено: {cnt or 0}\n"
        f"💰 Заработано: {total or 0}₽\n\n"
        f"• +20₽ за каждого друга\n"
        f"• +30% от первой покупки реферала",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=link)],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="start_menu")],
        ])
    )

# ПРОМОКОД
@dp.callback_query(F.data == "promo_enter")
async def promo_enter(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_promo_input)
    await cb.message.edit_text("🎟 Введите промокод:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="start_menu")]
    ]))

@dp.message(UserStates.waiting_promo_input)
async def apply_promo(msg: Message, state: FSMContext):
    code = msg.text.strip().upper()
    c.execute("SELECT discount, uses FROM promocodes WHERE code=? AND uses>0", (code,))
    promo = c.fetchone()
    if promo:
        c.execute("UPDATE promocodes SET uses=uses-1 WHERE code=?", (code,))
        c.execute("UPDATE users SET discount=? WHERE id=?", (promo[0], msg.from_user.id))
        conn.commit()
        await msg.answer(f"✅ Промокод активирован! Скидка {promo[0]}% на следующую покупку.", reply_markup=main_menu())
    else:
        await msg.answer("❌ Промокод не найден или истёк.")
    await state.clear()

# ПОДДЕРЖКА
@dp.callback_query(F.data == "support_menu")
async def support_menu(cb: types.CallbackQuery):
    await cb.message.edit_text("📞 *ПОДДЕРЖКА*\n\nОпишите вашу проблему:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать", callback_data="new_ticket")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="start_menu")],
    ]))

@dp.callback_query(F.data == "new_ticket")
async def new_ticket(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_ticket_text)
    await cb.message.answer("📝 Опишите проблему одним сообщением:")

@dp.message(UserStates.waiting_ticket_text)
async def save_ticket(msg: Message, state: FSMContext):
    c.execute("INSERT INTO tickets (user_id, username, message, created) VALUES (?, ?, ?, ?)",
              (msg.from_user.id, msg.from_user.username, msg.text, datetime.now().isoformat()))
    conn.commit()
    for aid in ADMIN_IDS:
        try: await bot.send_message(aid, f"📋 Тикет #{c.lastrowid} от @{msg.from_user.username}")
        except: pass
    await msg.answer("✅ Обращение принято! Ответ в течение часа.", reply_markup=main_menu())
    await state.clear()

# АДМИНКА
@dp.message(F.text == "/admin")
async def admin(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    await msg.answer("🔐 *Админ-панель*", parse_mode="Markdown", reply_markup=admin_kb())

@dp.message(F.text == "📊 Статистика")
async def admin_stats(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    c.execute("SELECT COUNT(*) FROM users"); u = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status='success'"); rev = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM keys_pool WHERE status='free'"); free = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM keys_pool WHERE status='sold'"); sold = c.fetchone()[0]
    await msg.answer(f"📊 *Статистика*\n👥 Юзеров: {u}\n💰 Выручка: {rev} Stars\n🔑 Свободных ключей: {free}\n🔑 Продано: {sold}", parse_mode="Markdown")

@dp.message(F.text == "🔑 Создать ключи")
async def gen_keys_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    c.execute("SELECT id, name FROM cheats")
    txt = "Выберите чит (введите ID):\n\n" + "\n".join([f"{c[0]} — {c[1]}" for c in c.fetchall()])
    await state.set_state(AdminStates.waiting_gen_cheat)
    await msg.answer(txt)

@dp.message(AdminStates.waiting_gen_cheat)
async def gen_cheat(msg: Message, state: FSMContext):
    try:
        await state.update_data(gc=int(msg.text))
        await state.set_state(AdminStates.waiting_gen_count)
        await msg.answer("Сколько ключей создать?")
    except: await msg.answer("❌ Введите число!")

@dp.message(AdminStates.waiting_gen_count)
async def gen_count(msg: Message, state: FSMContext):
    try:
        count = int(msg.text)
        data = await state.get_data()
        for _ in range(count):
            c.execute("INSERT INTO keys_pool (key, cheat_id, duration, status, created) VALUES (?, ?, 7, 'free', ?)",
                      (gen_key(), data['gc'], datetime.now().isoformat()))
        conn.commit()
        await msg.answer(f"✅ Создано {count} ключей")
        await state.clear()
    except: await msg.answer("❌ Введите число!")

@dp.message(F.text == "📢 Рассылка")
async def mass_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminStates.waiting_mass_text)
    await msg.answer("Введите текст рассылки:")

@dp.message(AdminStates.waiting_mass_text)
async def mass_send(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    c.execute("SELECT id FROM users WHERE banned=0")
    sent = 0
    for (uid,) in c.fetchall():
        try: await bot.send_message(uid, msg.text); sent += 1; await asyncio.sleep(0.05)
        except: pass
    await msg.answer(f"✅ Отправлено: {sent}"); await state.clear()

@dp.message(F.text == "🎟 Промокод")
async def promo_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminStates.waiting_promo_discount)
    await msg.answer("Процент скидки:")

@dp.message(AdminStates.waiting_promo_discount)
async def promo_disc(msg: Message, state: FSMContext):
    try:
        await state.update_data(pd=int(msg.text))
        await state.set_state(AdminStates.waiting_promo_uses)
        await msg.answer("Количество использований:")
    except: await msg.answer("❌ Введите число!")

@dp.message(AdminStates.waiting_promo_uses)
async def promo_uses(msg: Message, state: FSMContext):
    try:
        uses = int(msg.text)
        data = await state.get_data()
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        c.execute("INSERT INTO promocodes VALUES (?, ?, ?, ?)", (code, data['pd'], uses, uses))
        conn.commit()
        await msg.answer(f"✅ Промокод: `{code}`\nСкидка: {data['pd']}%\nИспользований: {uses}", parse_mode="Markdown")
        await state.clear()
    except: await msg.answer("❌ Введите число!")

@dp.message(F.text == "➕ Баланс")
async def add_bal_start(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminStates.waiting_add_balance_user)
    await msg.answer("ID пользователя:")

@dp.message(AdminStates.waiting_add_balance_user)
async def add_bal_uid(msg: Message, state: FSMContext):
    try:
        await state.update_data(uid=int(msg.text))
        await state.set_state(AdminStates.waiting_add_balance_amount)
        await msg.answer("Сумма:")
    except: await msg.answer("❌ Введите число!")

@dp.message(AdminStates.waiting_add_balance_amount)
async def add_bal_amt(msg: Message, state: FSMContext):
    try:
        amt = float(msg.text)
        data = await state.get_data()
        c.execute("UPDATE users SET balance=balance+? WHERE id=?", (amt, data['uid']))
        conn.commit()
        await msg.answer(f"✅ Баланс пополнен на {amt}₽"); await state.clear()
    except: await msg.answer("❌ Введите число!")

@dp.message(F.text == "📋 Тикеты")
async def admin_tickets(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    c.execute("SELECT id, user_id, message, status FROM tickets WHERE status='open' LIMIT 10")
    tickets = c.fetchall()
    if not tickets: await msg.answer("Нет открытых тикетов"); return
    for t in tickets:
        await msg.answer(f"📋 #{t[0]} | {t[1]}\n{t[2]}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"reply_{t[0]}")]
        ]))

@dp.callback_query(F.data.startswith("reply_"))
async def reply_start(cb: types.CallbackQuery, state: FSMContext):
    await state.update_data(tid=int(cb.data.split("_")[1]))
    await state.set_state(AdminStates.waiting_ticket_reply)
    await cb.message.answer("Введите ответ:")

@dp.message(AdminStates.waiting_ticket_reply)
async def reply_send(msg: Message, state: FSMContext):
    data = await state.get_data()
    c.execute("SELECT user_id FROM tickets WHERE id=?", (data['tid'],))
    if t := c.fetchone():
        c.execute("UPDATE tickets SET reply=?, status='closed' WHERE id=?", (msg.text, data['tid']))
        conn.commit()
        try: await bot.send_message(t[0], f"📞 Ответ поддержки:\n\n{msg.text}")
        except: pass
    await msg.answer("✅ Ответ отправлен"); await state.clear()

@dp.message(F.text == "🔙 Выход")
async def exit_admin(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Вы вышли из админ-панели", reply_markup=types.ReplyKeyboardRemove())

# HEALTH CHECK
async def health(request): return web.Response(text="OK")

async def run_web():
    app = web.Application()
    app.router.add_get('/', health)
    r = web.AppRunner(app)
    await r.setup()
    await web.TCPSite(r, '0.0.0.0', HEALTH_CHECK_PORT).start()

async def main():
    asyncio.create_task(run_web())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
