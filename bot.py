import asyncio
import logging
import hashlib
import random
import string
import json
from datetime import datetime, timedelta
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
    FSInputFile, BufferedInputFile
)
import aiohttp
from bs4 import BeautifulSoup
import sqlite3
import openpyxl

# ============ НАСТРОЙКИ ============
TOKEN = "8623163395:AAEWna0-DmFKdFvCO8z6NWeRcA-ybnR55Ss"
ADMIN_IDS = [8504186560]
USDT_ADDRESS = "ТВОЙ_USDT_TRC20"
CRYPTO_BOT_TOKEN = ""  # Токен от @CryptoBot если будете подключать
# ===================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ============ БАЗА ДАННЫХ ============
conn = sqlite3.connect('shop.db', check_same_thread=False)
c = conn.cursor()

c.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0,
        proxies TEXT,
        proxy_login TEXT,
        proxy_password TEXT,
        proxy_type TEXT,
        proxy_country TEXT,
        expiry TEXT,
        discount INTEGER DEFAULT 0,
        total_spent REAL DEFAULT 0,
        registered TEXT,
        banned INTEGER DEFAULT 0,
        language TEXT DEFAULT 'ru',
        auto_renew INTEGER DEFAULT 0
    );
    
    CREATE TABLE IF NOT EXISTS proxies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip TEXT,
        port TEXT,
        type TEXT,
        login TEXT,
        password TEXT,
        country TEXT,
        status TEXT,
        sold INTEGER DEFAULT 0,
        tier TEXT DEFAULT 'base',
        speed INTEGER DEFAULT 0,
        uptime REAL DEFAULT 100.0,
        last_check TEXT,
        added TEXT
    );
    
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_id INTEGER,
        amount REAL DEFAULT 20,
        date TEXT
    );
    
    CREATE TABLE IF NOT EXISTS promocodes (
        code TEXT PRIMARY KEY,
        discount INTEGER,
        uses INTEGER,
        max_uses INTEGER,
        created_by INTEGER,
        created TEXT
    );
    
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        currency TEXT,
        status TEXT,
        date TEXT,
        payload TEXT
    );
    
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        message TEXT,
        reply TEXT,
        status TEXT DEFAULT 'open',
        created TEXT,
        closed TEXT
    );
    
    CREATE TABLE IF NOT EXISTS proxy_pool (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip TEXT,
        port INTEGER,
        login TEXT,
        password TEXT,
        type TEXT,
        country TEXT,
        tier TEXT,
        status TEXT DEFAULT 'active',
        max_users INTEGER DEFAULT 1,
        current_users INTEGER DEFAULT 0,
        added TEXT
    );
''')
conn.commit()

# ============ ТОВАРЫ ============
PROXY_TIERS = {
    "base": {
        "price": 50,
        "name": "👤 Базовый",
        "speed": "до 10 Мбит/с",
        "anon": "HTTP - сайт видит прокси",
        "traffic": "Безлимит",
        "threads": 1,
        "features": ["Доступ к сайтам", "Смена IP каждые 30 мин"]
    },
    "anon": {
        "price": 150,
        "name": "🕵️ Анонимный",
        "speed": "до 50 Мбит/с",
        "anon": "HTTP(S) - высокая анонимность",
        "traffic": "Безлимит",
        "threads": 5,
        "features": ["Все сайты", "Соцсети", "Парсинг", "Смена IP каждые 15 мин"]
    },
    "elite": {
        "price": 300,
        "name": "👑 Elite",
        "speed": "до 100 Мбит/с",
        "anon": "SOCKS5 - полная анонимность",
        "traffic": "Безлимит",
        "threads": 50,
        "features": ["Всё включено", "Стриминг", "Игры", "Статический IP", "24/7 поддержка"]
    },
}

DURATIONS = {
    1: {"name": "1 день (тест)", "mult": 0},
    7: {"name": "1 неделя", "mult": 1},
    14: {"name": "2 недели", "mult": 1.8},
    30: {"name": "1 месяц", "mult": 3.5},
    90: {"name": "3 месяца", "mult": 9},
    365: {"name": "1 год", "mult": 30},
}

COUNTRIES = {
    "auto": "🌍 Авто",
    "ru": "🇷🇺 Россия",
    "us": "🇺🇸 США",
    "de": "🇩🇪 Германия",
    "nl": "🇳🇱 Нидерланды",
    "fr": "🇫🇷 Франция",
    "gb": "🇬🇧 Великобритания",
    "ua": "🇺🇦 Украина",
}

# ============ СОСТОЯНИЯ ============
class AdminStates(StatesGroup):
    waiting_mass_text = State()
    waiting_mass_photo = State()
    waiting_promo_code = State()
    waiting_promo_discount = State()
    waiting_promo_uses = State()
    waiting_ticket_reply = State()
    waiting_add_balance_user = State()
    waiting_add_balance_amount = State()
    waiting_ban_user = State()
    waiting_unban_user = State()
    waiting_search_user = State()
    waiting_proxy_add = State()

class UserStates(StatesGroup):
    waiting_ticket_text = State()
    waiting_promo_input = State()

# ============ ФУНКЦИИ ПРОКСИ ============
def generate_proxy_credentials():
    """Генерирует логин и пароль для прокси"""
    login = 'user_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    password = ''.join(random.choices(string.ascii_letters + string.digits + "!@#$%^&*", k=16))
    return login, password

async def fetch_proxies():
    """Парсинг бесплатных прокси"""
    sources = [
        'https://free-proxy-list.net/',
        'https://www.sslproxies.org/',
        'https://www.us-proxy.org/',
        'https://www.socks-proxy.net/',
    ]
    proxies = []
    async with aiohttp.ClientSession() as session:
        for url in sources:
            try:
                async with session.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'}) as resp:
                    html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                table = soup.find('table')
                if table:
                    for row in table.find_all('tr')[1:]:
                        cols = row.find_all('td')
                        if cols and len(cols) >= 7:
                            proxy_type = 'SOCKS5' if 'socks' in url else ('HTTPS' if 'yes' in cols[6].text.lower() else 'HTTP')
                            proxies.append({
                                'ip': cols[0].text.strip(),
                                'port': cols[1].text.strip(),
                                'type': proxy_type,
                                'country': cols[3].text.strip() if len(cols) > 3 else 'Unknown',
                            })
            except Exception as e:
                logger.error(f"Parse error {url}: {e}")
                continue
    return proxies

async def check_proxy(ip, port, proxy_type='HTTP'):
    """Проверка работоспособности прокси"""
    try:
        proxy_url = f'{proxy_type.lower()}://{ip}:{port}'
        async with aiohttp.ClientSession() as session:
            start = asyncio.get_event_loop().time()
            async with session.get(
                'http://httpbin.org/ip',
                proxy=proxy_url,
                timeout=8,
                headers={'User-Agent': 'Mozilla/5.0'}
            ) as resp:
                data = await resp.json()
                speed = asyncio.get_event_loop().time() - start
                
                # Проверяем что прокси реально работает и скрывает IP
                if resp.status == 200 and 'origin' in data:
                    return True, round(speed * 1000, 2), data.get('origin', '')
    except Exception as e:
        logger.debug(f"Proxy check failed {ip}:{port} - {e}")
    return False, 0, ''

async def check_proxy_with_auth(ip, port, login, password, proxy_type='HTTP'):
    """Проверка прокси с авторизацией"""
    try:
        proxy_url = f'{proxy_type.lower()}://{login}:{password}@{ip}:{port}'
        async with aiohttp.ClientSession() as session:
            start = asyncio.get_event_loop().time()
            async with session.get(
                'http://httpbin.org/ip',
                proxy=proxy_url,
                timeout=8,
                headers={'User-Agent': 'Mozilla/5.0'}
            ) as resp:
                data = await resp.json()
                speed = asyncio.get_event_loop().time() - start
                if resp.status == 200:
                    return True, round(speed * 1000, 2), data.get('origin', '')
    except:
        pass
    return False, 0, ''

async def update_proxy_pool():
    """Обновление пула прокси с проверкой работоспособности"""
    logger.info("Starting proxy pool update...")
    while True:
        try:
            proxies = await fetch_proxies()
            added = 0
            checked = 0
            
            for p in proxies:
                if checked >= 50:  # Проверяем не более 50 за цикл
                    break
                    
                c.execute("SELECT id FROM proxies WHERE ip=? AND port=?", (p['ip'], p['port']))
                if not c.fetchone():
                    checked += 1
                    is_working, speed, origin_ip = await check_proxy(p['ip'], p['port'], p['type'])
                    
                    if is_working:
                        login, password = generate_proxy_credentials()
                        # Определяем тир по скорости
                        if speed < 500:
                            tier = 'elite'
                        elif speed < 1000:
                            tier = 'anon'
                        else:
                            tier = 'base'
                        
                        c.execute(
                            """INSERT INTO proxies 
                            (ip, port, type, login, password, country, status, tier, speed, uptime, last_check, added) 
                            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, 100.0, ?, ?)""",
                            (p['ip'], p['port'], p['type'], login, password, 
                             p.get('country', 'Unknown'), tier, speed, datetime.now().isoformat(), datetime.now().isoformat())
                        )
                        added += 1
                        logger.info(f"Added proxy: {p['ip']}:{p['port']} [{p['type']}] Speed: {speed}ms")
            
            conn.commit()
            logger.info(f"Pool update complete. Added: {added}, Checked: {checked}")
            
            # Очистка старых нерабочих прокси
            c.execute("DELETE FROM proxies WHERE status='inactive' AND added < ?", 
                     ((datetime.now() - timedelta(days=1)).isoformat(),))
            conn.commit()
            
        except Exception as e:
            logger.error(f"Pool update error: {e}")
        
        await asyncio.sleep(600)  # Обновление каждые 10 минут

async def monitor_user_proxies():
    """Мониторинг прокси пользователей с авто-заменой"""
    logger.info("Starting user proxy monitor...")
    while True:
        try:
            c.execute("""
                SELECT u.id, u.proxies, u.proxy_login, u.proxy_password, u.proxy_type, u.expiry 
                FROM users u 
                WHERE u.proxies IS NOT NULL AND u.banned = 0
            """)
            
            for user_id, proxy, login, pwd, ptype, expiry in c.fetchall():
                if not proxy or not expiry:
                    continue
                
                try:
                    exp_date = datetime.fromisoformat(expiry)
                    if exp_date < datetime.now():
                        # Прокси истёк
                        c.execute("UPDATE users SET proxies=NULL, proxy_login=NULL, proxy_password=NULL, expiry=NULL, auto_renew=0 WHERE id=?", (user_id,))
                        conn.commit()
                        try:
                            await bot.send_message(
                                user_id,
                                "⚠️ Срок действия вашего прокси истёк.\n"
                                "Продлите в меню: /start"
                            )
                        except:
                            pass
                        continue
                    
                    # Проверяем прокси
                    ip, port = proxy.split(':')
                    is_working, speed, _ = await check_proxy_with_auth(
                        ip, port, login, pwd, ptype or 'HTTP'
                    )
                    
                    if not is_working:
                        # Авто-замена
                        c.execute("""
                            SELECT * FROM proxies 
                            WHERE sold=0 AND status='active' 
                            ORDER BY speed ASC LIMIT 1
                        """)
                        new_proxy = c.fetchone()
                        
                        if new_proxy:
                            new_proxy_str = f"{new_proxy[1]}:{new_proxy[2]}"
                            c.execute(
                                "UPDATE users SET proxies=?, proxy_login=?, proxy_password=?, proxy_type=? WHERE id=?",
                                (new_proxy_str, new_proxy[4], new_proxy[5], new_proxy[3], user_id)
                            )
                            c.execute("UPDATE proxies SET sold=1 WHERE id=?", (new_proxy[0],))
                            conn.commit()
                            
                            try:
                                await bot.send_message(
                                    user_id,
                                    "🔄 *Ваш прокси был автоматически заменён*\n\n"
                                    f"Причина: старый прокси перестал работать\n\n"
                                    f"*Новый прокси:*\n"
                                    f"`{new_proxy_str}`\n"
                                    f"Логин: `{new_proxy[4]}`\n"
                                    f"Пароль: `{new_proxy[5]}`\n"
                                    f"Тип: {new_proxy[3]}\n\n"
                                    f"Скорость: {new_proxy[7]} мс",
                                    parse_mode="Markdown"
                                )
                            except:
                                pass
                            
                            logger.info(f"Replaced proxy for user {user_id}")
                    
                except Exception as e:
                    logger.error(f"Monitor error for user {user_id}: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Monitor error: {e}")
        
        await asyncio.sleep(120)  # Проверка каждые 2 минуты

async def continuous_proxy_checking():
    """Непрерывная проверка всего пула прокси"""
    while True:
        try:
            c.execute("SELECT id, ip, port, type, login, password FROM proxies WHERE sold=0 AND status='active'")
            proxies = c.fetchall()
            
            for p_id, ip, port, ptype, login, pwd in proxies:
                is_working, speed, _ = await check_proxy_with_auth(ip, port, login, pwd, ptype)
                
                if is_working:
                    c.execute(
                        "UPDATE proxies SET speed=?, uptime=MIN(100, uptime+0.1), last_check=? WHERE id=?",
                        (speed, datetime.now().isoformat(), p_id)
                    )
                else:
                    c.execute(
                        "UPDATE proxies SET uptime=MAX(0, uptime-5), last_check=?, status=CASE WHEN uptime <= 20 THEN 'inactive' ELSE status END WHERE id=?",
                        (datetime.now().isoformat(), p_id)
                    )
            
            conn.commit()
        except Exception as e:
            logger.error(f"Continuous check error: {e}")
        
        await asyncio.sleep(300)  # Каждые 5 минут

# ============ КЛАВИАТУРЫ ============
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔓 Купить прокси", callback_data="buy_menu")],
        [InlineKeyboardButton(text="📋 Мои прокси", callback_data="my_proxies")],
        [InlineKeyboardButton(text="🔄 Проверить прокси", callback_data="check_my_proxy")],
        [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="topup_menu")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="ref_menu")],
        [InlineKeyboardButton(text="🎟 Промокод", callback_data="promo_enter")],
        [InlineKeyboardButton(text="📞 Поддержка", callback_data="support_menu")],
        [InlineKeyboardButton(text="ℹ️ О сервисе", callback_data="about")],
    ])

def buy_menu_kb():
    buttons = []
    for tid, tier in PROXY_TIERS.items():
        buttons.append([InlineKeyboardButton(
            text=f"{tier['name']} — от {tier['price']}₽",
            callback_data=f"tier_{tid}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def country_kb(tier_id):
    buttons = []
    for cid, cname in COUNTRIES.items():
        buttons.append([InlineKeyboardButton(
            text=cname, callback_data=f"country_{tier_id}_{cid}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"tier_{tier_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def duration_kb(tier_id, country):
    buttons = []
    for days, info in DURATIONS.items():
        if days == 1:
            price = 0
            label = f"{info['name']} — БЕСПЛАТНО"
        else:
            price = int(PROXY_TIERS[tier_id]['price'] * info['mult'])
            label = f"{info['name']} — {price}₽"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"buy_{tier_id}_{days}_{country}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"tier_{tier_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Пользователи"), KeyboardButton(text="🔍 Поиск юзера")],
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🎟 Промокоды"), KeyboardButton(text="🚫 Бан юзера")],
        [KeyboardButton(text="➕ Баланс юзеру"), KeyboardButton(text="📋 Тикеты"), KeyboardButton(text="📤 Экспорт БД")],
        [KeyboardButton(text="🔄 Обновить пул"), KeyboardButton(text="📈 Дашборд")],
        [KeyboardButton(text="🔙 Выход из админки")],
    ], resize_keyboard=True)

# ============ ОБРАБОТЧИКИ ============
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    username = message.from_user.username
    
    c.execute("SELECT id, banned FROM users WHERE id=?", (uid,))
    user = c.fetchone()
    
    if user and user[1] == 1:
        await message.answer("❌ Вы заблокированы.")
        return
    
    if not user:
        c.execute(
            "INSERT INTO users (id, username, balance, registered) VALUES (?, ?, 10, ?)",
            (uid, username, datetime.now().isoformat())
        )
        conn.commit()
        
        # Обработка реферальной ссылки
        args = message.text.split()
        if len(args) > 1 and args[1].startswith("ref_"):
            ref_hash = args[1][4:]
            c.execute("SELECT id FROM users WHERE id!=?", (uid,))
            for u in c.fetchall():
                if hashlib.md5(str(u[0]).encode()).hexdigest()[:8] == ref_hash:
                    c.execute(
                        "INSERT INTO referrals (referrer_id, referred_id, amount, date) VALUES (?, ?, 20, ?)",
                        (u[0], uid, datetime.now().isoformat())
                    )
                    c.execute("UPDATE users SET balance=balance+20 WHERE id=?", (u[0],))
                    conn.commit()
                    try:
                        await bot.send_message(u[0], "🎉 Новый реферал! +20₽ на баланс")
                    except:
                        pass
                    break
    
    await message.answer(
        "🌐 *RING PROXY BOT*\n\n"
        "🚀 Премиум прокси с автозаменой\n"
        "🔒 Полная анонимность\n"
        "⚡ Мгновенная выдача\n"
        "🔄 Бесплатная замена при сбоях\n"
        "💳 Оплата Stars, USDT, карты (скоро)\n\n"
        "💰 *Бонус: 10₽ на баланс*\n"
        "🎁 *Пробный период: 1 день бесплатно*",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "main_menu")
async def back_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🌐 *RING PROXY BOT*\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "buy_menu")
async def show_buy_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🔓 *Выберите тариф:*\n\n"
        "👤 *Базовый* — для обычного сёрфинга\n"
        "🕵️ *Анонимный* — для соцсетей и парсинга\n"
        "👑 *Elite* — максимальная скорость и анонимность\n\n"
        "🎁 *Доступен 1 день бесплатно!*",
        parse_mode="Markdown",
        reply_markup=buy_menu_kb()
    )

@dp.callback_query(F.data.startswith("tier_"))
async def show_tier_info(callback: types.CallbackQuery):
    tid = callback.data.split("_")[1]
    tier = PROXY_TIERS[tid]
    
    features = "\n".join([f"• {f}" for f in tier['features']])
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Выбрать страну", callback_data=f"countries_{tid}")],
        [InlineKeyboardButton(text="📋 Выбрать срок", callback_data=f"durations_{tid}_auto")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_menu")],
    ])
    
    await callback.message.edit_text(
        f"{tier['name']}\n\n"
        f"⚡ Скорость: {tier['speed']}\n"
        f"🔒 Анонимность: {tier['anon']}\n"
        f"📊 Трафик: {tier['traffic']}\n"
        f"🔗 Потоков: {tier['threads']}\n\n"
        f"*Возможности:*\n{features}\n\n"
        f"💰 Цена: от {tier['price']}₽/нед",
        parse_mode="Markdown",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("countries_"))
async def show_countries(callback: types.CallbackQuery):
    tid = callback.data.split("_")[1]
    await callback.message.edit_text(
        f"{PROXY_TIERS[tid]['name']}\n\n🌍 Выберите страну:",
        reply_markup=country_kb(tid)
    )

@dp.callback_query(F.data.startswith("country_"))
async def show_durations_with_country(callback: types.CallbackQuery):
    _, tid, country = callback.data.split("_")
    await callback.message.edit_text(
        f"{PROXY_TIERS[tid]['name']}\n{COUNTRIES.get(country, '🌍 Авто')}\n\n📅 Выберите срок:",
        reply_markup=duration_kb(tid, country)
    )

@dp.callback_query(F.data.startswith("durations_"))
async def show_durations_direct(callback: types.CallbackQuery):
    _, tid, country = callback.data.split("_")
    await callback.message.edit_text(
        f"{PROXY_TIERS[tid]['name']}\n📅 Выберите срок:",
        reply_markup=duration_kb(tid, country)
    )

@dp.callback_query(F.data.startswith("buy_"))
async def confirm_purchase(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    tid = parts[1]
    days = int(parts[2])
    country = parts[3] if len(parts) > 3 else 'auto'
    
    tier = PROXY_TIERS[tid]
    dur = DURATIONS[days]
    
    if days == 1:
        price = 0
        final = 0
        label = "БЕСПЛАТНО (пробный)"
    else:
        price = int(tier['price'] * dur['mult'])
        c.execute("SELECT discount FROM users WHERE id=?", (callback.from_user.id,))
        user = c.fetchone()
        disc = user[0] if user and user[0] else 0
        final = int(price * (1 - disc/100))
        label = f"{final}₽"
    
    if final == 0:
        # Бесплатный пробный период
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Активировать бесплатно", callback_data=f"activate_free_{tid}_{country}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"tier_{tid}")],
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐ Stars ({final}⭐)", callback_data=f"paystars_{tid}_{days}_{country}_{final}")],
            [InlineKeyboardButton(text="💎 USDT TRC20", callback_data=f"payusdt_{tid}_{days}_{country}_{price}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"durations_{tid}_{country}")],
        ])
    
    await callback.message.edit_text(
        f"🛒 *Оформление заказа*\n\n"
        f"📦 Товар: {tier['name']}\n"
        f"🌍 Страна: {COUNTRIES.get(country, 'Авто')}\n"
        f"📅 Срок: {dur['name']}\n"
        f"💰 Цена: {label}\n\n"
        f"🔒 После оплаты вы получите:\n"
        f"• IP:Port\n"
        f"• Логин и пароль\n"
        f"• Тип прокси\n"
        f"• Инструкцию по настройке",
        parse_mode="Markdown",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("activate_free_"))
async def activate_free_trial(callback: types.CallbackQuery):
    _, _, tid, country = callback.data.split("_")
    
    c.execute("SELECT id FROM payments WHERE user_id=? AND payload LIKE '%trial%'", (callback.from_user.id,))
    if c.fetchone():
        await callback.answer("❌ Вы уже использовали пробный период!", show_alert=True)
        return
    
    c.execute("""
        SELECT * FROM proxies 
        WHERE sold=0 AND status='active' AND tier=? 
        ORDER BY speed ASC LIMIT 1
    """, (tid,))
    proxy = c.fetchone()
    
    if not proxy:
        c.execute("SELECT * FROM proxies WHERE sold=0 AND status='active' ORDER BY speed ASC LIMIT 1")
        proxy = c.fetchone()
    
    if proxy:
        proxy_str = f"{proxy[1]}:{proxy[2]}"
        expiry = datetime.now() + timedelta(days=1)
        
        c.execute("UPDATE proxies SET sold=1 WHERE id=?", (proxy[0],))
        c.execute(
            "UPDATE users SET proxies=?, proxy_login=?, proxy_password=?, proxy_type=?, proxy_country=?, expiry=? WHERE id=?",
            (proxy_str, proxy[4], proxy[5], proxy[3], country, expiry.isoformat(), callback.from_user.id)
        )
        c.execute(
            "INSERT INTO payments (user_id, amount, currency, status, date, payload) VALUES (?, 0, 'FREE', 'success', ?, 'trial')",
            (callback.from_user.id, datetime.now().isoformat())
        )
        conn.commit()
        
        setup_guide = get_setup_guide(proxy_str, proxy[4], proxy[5], proxy[3])
        
        await callback.message.edit_text(
            f"🎁 *Пробный период активирован!*\n\n"
            f"📋 *Данные прокси:*\n"
            f"🔗 IP:Port: `{proxy_str}`\n"
            f"👤 Логин: `{proxy[4]}`\n"
            f"🔑 Пароль: `{proxy[5]}`\n"
            f"📡 Тип: {proxy[3]}\n"
            f"🌍 Страна: {COUNTRIES.get(country, 'Авто')}\n"
            f"⚡ Скорость: {proxy[7]} мс\n"
            f"📅 Действует до: {expiry.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"{setup_guide}",
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            "❌ Временно нет доступных прокси. Попробуйте позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
            ])
        )

@dp.callback_query(F.data.startswith("paystars_"))
async def pay_with_stars(callback: types.CallbackQuery):
    _, tid, days, country, final = callback.data.split("_")
    days = int(days)
    final = int(final)
    
    tier = PROXY_TIERS[tid]
    dur = DURATIONS[days]
    
    await callback.message.answer_invoice(
        title=f"Прокси {tier['name']}",
        description=f"{dur['name']} | {COUNTRIES.get(country, 'Авто')}",
        payload=f"proxy_{tid}_{days}_{country}",
        provider_token="",
        currency="XTR",
        prices=[types.LabeledPrice(label=f"{tier['name']} - {dur['name']}", amount=final)],
        start_parameter=f"buy_{tid}",
        need_name=False,
        need_phone_number=False,
        need_email=False,
    )
    
    await callback.message.edit_text(
        "✅ Счёт выставлен! Оплатите через Telegram Stars",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
        ])
    )

@dp.message(F.successful_payment)
async def on_payment_success(message: types.Message):
    payload = message.successful_payment.invoice_payload
    _, tid, days, country = payload.split("_")
    days = int(days)
    
    await activate_proxy_for_user(message.from_user.id, tid, days, country, message.successful_payment.total_amount, 'XTR')
    
    await message.answer(
        "✅ *Оплата получена! Прокси активирован!*\n\n"
        "Используйте /start для просмотра данных прокси.",
        parse_mode="Markdown"
    )

async def activate_proxy_for_user(user_id, tier_id, days, country, amount, currency):
    """Активация прокси для пользователя после оплаты"""
    c.execute("""
        SELECT * FROM proxies 
        WHERE sold=0 AND status='active' AND tier=? 
        ORDER BY speed ASC LIMIT 1
    """, (tier_id,))
    proxy = c.fetchone()
    
    if not proxy:
        c.execute("SELECT * FROM proxies WHERE sold=0 AND status='active' ORDER BY speed ASC LIMIT 1")
        proxy = c.fetchone()
    
    if proxy:
        proxy_str = f"{proxy[1]}:{proxy[2]}"
        expiry = datetime.now() + timedelta(days=days)
        
        c.execute("UPDATE proxies SET sold=1 WHERE id=?", (proxy[0],))
        c.execute(
            "UPDATE users SET proxies=?, proxy_login=?, proxy_password=?, proxy_type=?, proxy_country=?, expiry=?, discount=0 WHERE id=?",
            (proxy_str, proxy[4], proxy[5], proxy[3], country, expiry.isoformat(), user_id)
        )
        c.execute(
            "INSERT INTO payments (user_id, amount, currency, status, date, payload) VALUES (?, ?, ?, 'success', ?, ?)",
            (user_id, amount, currency, datetime.now().isoformat(), f"{tier_id}_{days}_{country}")
        )
        
        # Начисление рефереру
        c.execute("SELECT referrer_id FROM referrals WHERE referred_id=? AND amount=20", (user_id,))
        ref = c.fetchone()
        if ref:
            bonus = int(amount * 0.3) if amount > 0 else 0
            if bonus > 0:
                c.execute("UPDATE referrals SET amount=amount+? WHERE referred_id=?", (bonus, user_id))
                c.execute("UPDATE users SET balance=balance+? WHERE id=?", (bonus, ref[0]))
                try:
                    await bot.send_message(ref[0], f"🎉 Реферал купил прокси! +{bonus}₽")
                except:
                    pass
        
        conn.commit()
        
        setup_guide = get_setup_guide(proxy_str, proxy[4], proxy[5], proxy[3])
        
        try:
            await bot.send_message(
                user_id,
                f"✅ *Прокси активирован!*\n\n"
                f"📋 *Данные вашего прокси:*\n\n"
                f"🔗 *IP:Port:* `{proxy_str}`\n"
                f"👤 *Логин:* `{proxy[4]}`\n"
                f"🔑 *Пароль:* `{proxy[5]}`\n"
                f"📡 *Тип:* {proxy[3]}\n"
                f"🌍 *Страна:* {COUNTRIES.get(country, 'Авто')}\n"
                f"⚡ *Скорость:* {proxy[7]} мс\n"
                f"📅 *Действует до:* {expiry.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"{setup_guide}\n\n"
                f"🔄 *Автозамена включена* — если прокси упадёт, заменим автоматически.",
                parse_mode="Markdown"
            )
        except:
            pass
        
        return True
    
    return False

def get_setup_guide(proxy_str, login, password, proxy_type):
    """Генерация инструкции по настройке"""
    ip, port = proxy_str.split(':')
    
    if proxy_type == 'SOCKS5':
        return (
            "📖 *Настройка SOCKS5:*\n\n"
            "*Браузер (Firefox):*\n"
            "Настройки → Сеть → Прокси\n"
            f"SOCKS5: `{ip}` : `{port}`\n"
            f"Логин: `{login}`\n"
            f"Пароль: `{password}`\n\n"
            "*Telegram:*\n"
            "Настройки → Данные → Прокси\n"
            f"SOCKS5: `{ip}` : `{port}`\n"
            f"Логин: `{login}`\n"
            f"Пароль: `{password}`"
        )
    else:
        return (
            "📖 *Настройка HTTP(S):*\n\n"
            "*Браузер (Chrome/Firefox):*\n"
            "Настройки → Прокси\n"
            f"{proxy_type}: `{ip}` : `{port}`\n"
            f"Логин: `{login}`\n"
            f"Пароль: `{password}`\n\n"
            "*Windows:*\n"
            "Параметры → Сеть → Прокси\n"
            f"Адрес: `{ip}` Порт: `{port}`"
        )

@dp.callback_query(F.data == "my_proxies")
async def my_proxies(callback: types.CallbackQuery):
    c.execute(
        "SELECT proxies, proxy_login, proxy_password, proxy_type, proxy_country, expiry FROM users WHERE id=?",
        (callback.from_user.id,)
    )
    u = c.fetchone()
    
    if not u or not u[0]:
        await callback.message.edit_text(
            "У вас нет активных прокси.\n\n"
            "🎁 *Доступен 1 день бесплатно!*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔓 Купить", callback_data="buy_menu")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
            ])
        )
        return
    
    proxy, login, pwd, ptype, country, expiry = u
    
    try:
        exp = datetime.fromisoformat(expiry)
        now = datetime.now()
        days_left = max(0, (exp - now).days)
        hours_left = max(0, int((exp - now).total_seconds() / 3600))
        status = '🟢 Активен' if exp > now else '🔴 Истёк'
    except:
        days_left = 0
        hours_left = 0
        status = '🔴 Истёк'
    
    setup_guide = get_setup_guide(proxy, login, pwd, ptype) if status == '🟢 Активен' else ''
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Проверить сейчас", callback_data="check_my_proxy")],
        [InlineKeyboardButton(text="🔄 Продлить", callback_data="buy_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
    ])
    
    await callback.message.edit_text(
        f"📋 *Ваш прокси*\n\n"
        f"🔗 `{proxy}`\n"
        f"👤 Логин: `{login}`\n"
        f"🔑 Пароль: `{pwd}`\n"
        f"📡 Тип: {ptype}\n"
        f"🌍 Страна: {COUNTRIES.get(country, 'Авто')}\n"
        f"{status}\n"
        f"⏳ Осталось: {days_left} дн. {hours_left % 24} ч.\n"
        f"📅 До: {exp.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"{setup_guide}",
        parse_mode="Markdown",
        reply_markup=kb
    )

@dp.callback_query(F.data == "check_my_proxy")
async def check_my_proxy(callback: types.CallbackQuery):
    c.execute(
        "SELECT proxies, proxy_login, proxy_password, proxy_type FROM users WHERE id=?",
        (callback.from_user.id,)
    )
    u = c.fetchone()
    
    if not u or not u[0]:
        await callback.answer("❌ У вас нет активного прокси", show_alert=True)
        return
    
    await callback.answer("🔄 Проверяю прокси...")
    
    ip, port = u[0].split(':')
    is_working, speed, origin = await check_proxy_with_auth(ip, port, u[1], u[2], u[3] or 'HTTP')
    
    if is_working:
        await callback.message.answer(
            f"✅ *Прокси работает!*\n\n"
            f"⚡ Скорость: {speed} мс\n"
            f"🌐 Внешний IP: `{origin}`\n\n"
            f"Всё в порядке, можете использовать.",
            parse_mode="Markdown"
        )
    else:
        await callback.message.answer(
            "❌ *Прокси не отвечает*\n\n"
            "Сейчас попробуем заменить автоматически...",
            parse_mode="Markdown"
        )
        
        c.execute("SELECT * FROM proxies WHERE sold=0 AND status='active' ORDER BY speed ASC LIMIT 1")
        new_proxy = c.fetchone()
        
        if new_proxy:
            new_str = f"{new_proxy[1]}:{new_proxy[2]}"
            c.execute(
                "UPDATE users SET proxies=?, proxy_login=?, proxy_password=?, proxy_type=? WHERE id=?",
                (new_str, new_proxy[4], new_proxy[5], new_proxy[3], callback.from_user.id)
            )
            c.execute("UPDATE proxies SET sold=1 WHERE id=?", (new_proxy[0],))
            conn.commit()
            
            await callback.message.answer(
                f"✅ *Прокси заменён!*\n\n"
                f"🔗 `{new_str}`\n"
                f"👤 Логин: `{new_proxy[4]}`\n"
                f"🔑 Пароль: `{new_proxy[5]}`\n"
                f"⚡ Скорость: {new_proxy[7]} мс",
                parse_mode="Markdown"
            )
        else:
            await callback.message.answer(
                "❌ Нет свободных прокси для замены. Попробуйте позже.",
                reply_markup=main_menu()
            )

@dp.callback_query(F.data == "topup_menu")
async def topup_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💰 *Пополнение баланса*\n\n"
        "⭐ *Telegram Stars* — мгновенно\n"
        "💎 *USDT TRC20* — ручная проверка\n"
        "💳 *Банковские карты* — скоро\n"
        "₽ *СБП / Гривны / Доллары / Евро* — скоро",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="topup_stars")],
            [InlineKeyboardButton(text="💎 USDT TRC20", callback_data="topup_usdt")],
            [InlineKeyboardButton(text="💳 Карты (скоро)", callback_data="topup_soon")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
        ])
    )

@dp.callback_query(F.data == "topup_soon")
async def topup_soon(callback: types.CallbackQuery):
    await callback.answer(
        "🔄 Оплата гривнами, рублями, долларами, евро и картами будет в следующем обновлении!",
        show_alert=True
    )

@dp.callback_query(F.data == "ref_menu")
async def ref_menu(callback: types.CallbackQuery):
    ref_hash = hashlib.md5(str(callback.from_user.id).encode()).hexdigest()[:8]
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{ref_hash}"
    
    c.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM referrals WHERE referrer_id=?", (callback.from_user.id,))
    cnt, total = c.fetchone()
    
    await callback.message.edit_text(
        "👥 *Реферальная система*\n\n"
        f"🔗 Ваша ссылка:\n`{ref_link}`\n\n"
        f"👤 Приглашено: {cnt or 0}\n"
        f"💰 Заработано: {total or 0}₽\n\n"
        "💎 *Бонусы:*\n"
        "• +20₽ за каждого друга\n"
        "• +30% от первой покупки реферала\n\n"
        "📤 Отправьте ссылку друзьям!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=ref_link)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
        ])
    )

@dp.callback_query(F.data == "promo_enter")
async def promo_enter(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_promo_input)
    await callback.message.edit_text(
        "🎟 Введите промокод:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="main_menu")]
        ])
    )

@dp.message(UserStates.waiting_promo_input)
async def apply_promo(message: types.Message, state: FSMContext):
    code = message.text.strip().upper()
    
    c.execute("SELECT discount, uses FROM promocodes WHERE code=? AND uses>0", (code,))
    promo = c.fetchone()
    
    if not promo:
        await message.answer("❌ Промокод не найден или истёк")
        await state.clear()
        return
    
    c.execute("UPDATE promocodes SET uses=uses-1 WHERE code=?", (code,))
    c.execute("UPDATE users SET discount=? WHERE id=?", (promo[0], message.from_user.id))
    conn.commit()
    
    await message.answer(
        f"✅ Промокод активирован! Скидка {promo[0]}% на следующую покупку.",
        reply_markup=main_menu()
    )
    await state.clear()

@dp.callback_query(F.data == "support_menu")
async def support_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📞 *Поддержка*\n\n"
        "Опишите вашу проблему одним сообщением.\n"
        "Время ответа: до 1 часа.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Написать", callback_data="new_ticket")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
        ])
    )

@dp.callback_query(F.data == "new_ticket")
async def new_ticket(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_ticket_text)
    await callback.message.answer(
        "📝 Опишите вашу проблему:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="support_menu")]
        ])
    )

@dp.message(UserStates.waiting_ticket_text)
async def save_ticket(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return
    
    c.execute(
        "INSERT INTO tickets (user_id, username, message, created) VALUES (?, ?, ?, ?)",
        (message.from_user.id, message.from_user.username, message.text, datetime.now().isoformat())
    )
    conn.commit()
    
    ticket_id = c.lastrowid
    
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(
                aid,
                f"📋 *Новый тикет #{ticket_id}*\n"
                f"От: @{message.from_user.username} (ID: {message.from_user.id})\n"
                f"Сообщение: {message.text}",
                parse_mode="Markdown"
            )
        except:
            pass
    
    await message.answer(
        "✅ Ваше обращение принято! Ответ придёт в ближайшее время.",
        reply_markup=main_menu()
    )
    await state.clear()

@dp.callback_query(F.data == "about")
async def about(callback: types.CallbackQuery):
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM proxies WHERE status='active' AND sold=0")
    avail = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM proxies WHERE status='active'")
    total_proxies = c.fetchone()[0]
    
    await callback.message.edit_text(
        "🌐 *RING PROXY BOT*\n\n"
        f"👥 Пользователей: {total}\n"
        f"🟢 Свободных прокси: {avail}\n"
        f"📦 Всего в пуле: {total_proxies}\n\n"
        "⚡ Автообновление пула\n"
        "🔄 Автозамена при сбоях\n"
        "🔒 Полная анонимность\n\n"
        "💳 Оплата: Stars, USDT\n"
        "💎 Скоро: карты, СБП, валюты\n\n"
        "📞 Поддержка: кнопка в меню",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
        ])
    )

# ============ АДМИНКА ============
@dp.message(F.text == "/admin")
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer(
        "🔐 *Админ-панель RING PROXY*\n\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=admin_kb()
    )

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE proxies IS NOT NULL")
    active_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE banned=1")
    banned = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='success'")
    revenue = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM proxies WHERE sold=0 AND status='active'")
    avail = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM proxies")
    total_proxies = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM tickets WHERE status='open'")
    tickets = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM referrals")
    refs = c.fetchone()[0]
    
    await message.answer(
        f"📊 *Статистика бота*\n\n"
        f"👥 Всего юзеров: {total_users}\n"
        f"🟢 Активных: {active_users}\n"
        f"🚫 Забанено: {banned}\n"
        f"💰 Выручка: {revenue} Stars\n"
        f"🛒 Свободных прокси: {avail}\n"
        f"📦 Всего прокси в БД: {total_proxies}\n"
        f"📋 Открытых тикетов: {tickets}\n"
        f"👥 Рефералов: {refs}",
        parse_mode="Markdown"
    )

@dp.message(F.text == "📈 Дашборд")
async def admin_dashboard(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Статистика за 7 дней
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    c.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payments WHERE status='success' AND date>?", (week_ago,))
    sales_week, revenue_week = c.fetchone()
    
    c.execute("SELECT COUNT(*) FROM users WHERE registered>?", (week_ago,))
    new_users_week = c.fetchone()[0]
    
    # Топ прокси по продажам
    c.execute("""
        SELECT tier, COUNT(*) as cnt FROM payments 
        WHERE status='success' 
        GROUP BY tier ORDER BY cnt DESC
    """)
    top_tiers = c.fetchall()
    
    text = "📈 *Дашборд (7 дней)*\n\n"
    text += f"🛒 Продаж: {sales_week or 0}\n"
    text += f"💰 Выручка: {revenue_week or 0} Stars\n"
    text += f"👥 Новых юзеров: {new_users_week}\n\n"
    text += "*Топ тарифов:*\n"
    for tier, cnt in top_tiers:
        text += f"• {PROXY_TIERS.get(tier, {}).get('name', tier)}: {cnt} шт.\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "👥 Пользователи")
async def admin_users(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    c.execute("""
        SELECT id, username, balance, proxies, banned FROM users 
        ORDER BY id DESC LIMIT 15
    """)
    users = c.fetchall()
    
    text = "👥 *Последние пользователи:*\n\n"
    for u in users:
        status = "🚫" if u[4] else ("🟢" if u[3] else "⚪")
        text += f"{status} `{u[0]}` @{u[1] or '—'} | {u[2]}₽\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "🔍 Поиск юзера")
async def search_user_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await state.set_state(AdminStates.waiting_search_user)
    await message.answer("Введите ID или @username:")

@dp.message(AdminStates.waiting_search_user)
async def search_user_result(message: types.Message, state: FSMContext):
    query = message.text.strip().replace('@', '')
    
    if query.isdigit():
        c.execute("SELECT * FROM users WHERE id=?", (int(query),))
    else:
        c.execute("SELECT * FROM users WHERE username=?", (query,))
    
    user = c.fetchone()
    
    if not user:
        await message.answer("❌ Пользователь не найден")
        await state.clear()
        return
    
    c.execute("SELECT COUNT(*) FROM payments WHERE user_id=? AND status='success'", (user[0],))
    purchases = c.fetchone()[0]
    
    c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE user_id=? AND status='success'", (user[0],))
    total_spent = c.fetchone()[0]
    
    text = (
        f"👤 *Пользователь*\n\n"
        f"ID: `{user[0]}`\n"
        f"Username: @{user[1] or '—'}\n"
        f"Баланс: {user[2]}₽\n"
        f"Прокси: {'Да' if user[3] else 'Нет'}\n"
        f"Действует до: {user[6] or '—'}\n"
        f"Забанен: {'Да' if user[8] else 'Нет'}\n"
        f"Покупок: {purchases}\n"
        f"Потрачено: {total_spent} Stars\n"
        f"Зарегистрирован: {user[9] or '—'}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Бан", callback_data=f"ban_user_{user[0]}")],
        [InlineKeyboardButton(text="✅ Разбан", callback_data=f"unban_user_{user[0]}")],
        [InlineKeyboardButton(text="💰 Пополнить", callback_data=f"add_balance_{user[0]}")],
    ])
    
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)
    await state.clear()

@dp.message(F.text == "🚫 Бан юзера")
async def ban_user_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await state.set_state(AdminStates.waiting_ban_user)
    await message.answer("Введите ID пользователя для бана:")

@dp.message(AdminStates.waiting_ban_user)
async def ban_user_do(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        c.execute("UPDATE users SET banned=1 WHERE id=?", (uid,))
        conn.commit()
        await message.answer(f"✅ Пользователь {uid} забанен")
        try:
            await bot.send_message(uid, "❌ Вы были заблокированы.")
        except:
            pass
    except:
        await message.answer("❌ Неверный ID")
    await state.clear()

@dp.message(F.text == "📢 Рассылка")
async def mass_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await state.set_state(AdminStates.waiting_mass_text)
    await message.answer(
        "Введите текст рассылки (поддерживает Markdown):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_mass")]
        ])
    )

@dp.message(AdminStates.waiting_mass_text)
async def mass_send(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    c.execute("SELECT id FROM users WHERE banned=0")
    users = c.fetchall()
    
    sent = 0
    failed = 0
    
    progress_msg = await message.answer(f"📢 Отправка... 0/{len(users)}")
    
    for i, (uid,) in enumerate(users):
        try:
            await bot.send_message(uid, message.text, parse_mode="Markdown")
            sent += 1
        except:
            failed += 1
        
        if i % 10 == 0:
            try:
                await progress_msg.edit_text(f"📢 Отправка... {sent}/{len(users)}")
            except:
                pass
        
        await asyncio.sleep(0.05)
    
    await progress_msg.edit_text(f"✅ Рассылка завершена!\nОтправлено: {sent}\nОшибок: {failed}")
    await state.clear()

@dp.message(F.text == "🎟 Промокоды")
async def admin_promo_menu(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    c.execute("SELECT * FROM promocodes ORDER BY created DESC LIMIT 20")
    codes = c.fetchall()
    
    text = "🎟 *Промокоды:*\n\n"
    if codes:
        for cd in codes:
            text += f"`{cd[0]}` — скидка {cd[1]}%, {cd[2]}/{cd[3]} исп.\n"
    else:
        text += "Нет промокодов\n"
    
    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать", callback_data="create_promo")],
        ])
    )

@dp.callback_query(F.data == "create_promo")
async def create_promo_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_promo_discount)
    await callback.message.answer("Введите процент скидки (число):")

@dp.message(AdminStates.waiting_promo_discount)
async def promo_discount(message: types.Message, state: FSMContext):
    try:
        discount = int(message.text)
        await state.update_data(promo_discount=discount)
        await state.set_state(AdminStates.waiting_promo_uses)
        await message.answer("Введите количество использований:")
    except:
        await message.answer("❌ Введите число!")

@dp.message(AdminStates.waiting_promo_uses)
async def promo_uses(message: types.Message, state: FSMContext):
    try:
        uses = int(message.text)
        data = await state.get_data()
        discount = data['promo_discount']
        
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        c.execute(
            "INSERT INTO promocodes (code, discount, uses, max_uses, created_by, created) VALUES (?, ?, ?, ?, ?, ?)",
            (code, discount, uses, uses, message.from_user.id, datetime.now().isoformat())
        )
        conn.commit()
        
        await message.answer(
            f"✅ Промокод создан!\n\n"
            f"Код: `{code}`\n"
            f"Скидка: {discount}%\n"
            f"Использований: {uses}",
            parse_mode="Markdown"
        )
        await state.clear()
    except:
        await message.answer("❌ Введите число!")

@dp.message(F.text == "➕ Баланс юзеру")
async def add_balance_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await state.set_state(AdminStates.waiting_add_balance_user)
    await message.answer("Введите ID пользователя:")

@dp.message(AdminStates.waiting_add_balance_user)
async def add_balance_user(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        await state.update_data(add_bal_user=uid)
        await state.set_state(AdminStates.waiting_add_balance_amount)
        await message.answer("Введите сумму:")
    except:
        await message.answer("❌ Введите число!")

@dp.message(AdminStates.waiting_add_balance_amount)
async def add_balance_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        data = await state.get_data()
        uid = data['add_bal_user']
        
        c.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))
        conn.commit()
        
        await message.answer(f"✅ Баланс пользователя {uid} пополнен на {amount}₽")
        
        try:
            await bot.send_message(uid, f"💰 Ваш баланс пополнен на {amount}₽ администратором!")
        except:
            pass
        
        await state.clear()
    except:
        await message.answer("❌ Введите корректную сумму!")

@dp.message(F.text == "📋 Тикеты")
async def admin_tickets(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    c.execute("SELECT id, user_id, username, message, status, created FROM tickets WHERE status='open' LIMIT 10")
    tickets = c.fetchall()
    
    if not tickets:
        await message.answer("✅ Нет открытых тикетов")
        return
    
    for t in tickets:
        await message.answer(
            f"📋 *Тикет #{t[0]}*\n"
            f"От: @{t[2] or '—'} (ID: {t[1]})\n"
            f"Дата: {t[5]}\n"
            f"Статус: {t[4]}\n\n"
            f"Сообщение: {t[3]}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"reply_ticket_{t[0]}")],
                [InlineKeyboardButton(text="✅ Закрыть", callback_data=f"close_ticket_{t[0]}")],
            ])
        )

@dp.callback_query(F.data.startswith("reply_ticket_"))
async def reply_ticket_start(callback: types.CallbackQuery, state: FSMContext):
    tid = int(callback.data.split("_")[2])
    await state.update_data(reply_ticket_id=tid)
    await state.set_state(AdminStates.waiting_ticket_reply)
    await callback.message.answer(f"Введите ответ на тикет #{tid}:")

@dp.message(AdminStates.waiting_ticket_reply)
async def reply_ticket_send(message: types.Message, state: FSMContext):
    data = await state.get_data()
    tid = data['reply_ticket_id']
    
    c.execute("SELECT user_id FROM tickets WHERE id=?", (tid,))
    ticket = c.fetchone()
    
    if ticket:
        c.execute(
            "UPDATE tickets SET reply=?, status='closed', closed=? WHERE id=?",
            (message.text, datetime.now().isoformat(), tid)
        )
        conn.commit()
        
        try:
            await bot.send_message(
                ticket[0],
                f"📞 *Ответ поддержки (тикет #{tid}):*\n\n{message.text}",
                parse_mode="Markdown"
            )
        except:
            pass
    
    await message.answer("✅ Ответ отправлен, тикет закрыт")
    await state.clear()

@dp.message(F.text == "📤 Экспорт БД")
async def export_db(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Экспорт в Excel
    wb = openpyxl.Workbook()
    
    # Лист пользователей
    ws_users = wb.active
    ws_users.title = "Пользователи"
    ws_users.append(["ID", "Username", "Баланс", "Прокси", "Истекает", "Забанен", "Дата рег."])
    
    c.execute("SELECT id, username, balance, proxies, expiry, banned, registered FROM users")
    for row in c.fetchall():
        ws_users.append(list(row))
    
    # Лист платежей
    ws_payments = wb.create_sheet("Платежи")
    ws_payments.append(["ID", "User ID", "Сумма", "Валюта", "Статус", "Дата"])
    
    c.execute("SELECT * FROM payments")
    for row in c.fetchall():
        ws_payments.append(list(row))
    
    # Сохраняем в BytesIO
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    await message.answer_document(
        BufferedInputFile(output.read(), f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"),
        caption="📤 Экспорт базы данных"
    )

@dp.message(F.text == "🔄 Обновить пул")
async def force_update_pool(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer("🔄 Запускаю принудительное обновление пула...")
    
    proxies = await fetch_proxies()
    added = 0
    
    for p in proxies[:20]:
        c.execute("SELECT id FROM proxies WHERE ip=? AND port=?", (p['ip'], p['port']))
        if not c.fetchone():
            is_working, speed, _ = await check_proxy(p['ip'], p['port'], p['type'])
            if is_working:
                login, password = generate_proxy_credentials()
                if speed < 500:
                    tier = 'elite'
                elif speed < 1000:
                    tier = 'anon'
                else:
                    tier = 'base'
                
                c.execute(
                    "INSERT INTO proxies (ip, port, type, login, password, country, status, tier, speed, uptime, last_check, added) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, 100.0, ?, ?)",
                    (p['ip'], p['port'], p['type'], login, password, p.get('country', 'Unknown'), tier, speed, datetime.now().isoformat(), datetime.now().isoformat())
                )
                added += 1
    
    conn.commit()
    await message.answer(f"✅ Пул обновлён! Добавлено {added} новых прокси.")

@dp.message(F.text == "🔙 Выход из админки")
async def exit_admin(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Вы вышли из админ-панели", reply_markup=types.ReplyKeyboardRemove())

# ============ ЗАПУСК ============
async def on_startup():
    logger.info("Starting RING PROXY BOT...")
    asyncio.create_task(update_proxy_pool())
    asyncio.create_task(monitor_user_proxies())
    asyncio.create_task(continuous_proxy_checking())
    logger.info("Bot started successfully!")

async def main():
    await on_startup()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())