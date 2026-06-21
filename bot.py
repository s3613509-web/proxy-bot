import asyncio
import logging
import hashlib
import random
import string
import json
import os
from datetime import datetime, timedelta
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
    FSInputFile, BufferedInputFile, LabeledPrice, Message,
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiohttp
from aiohttp import web
from bs4 import BeautifulSoup
import sqlite3
import openpyxl

# ============ НАСТРОЙКИ ============
TOKEN = "8623163395:AAEWna0-DmFKdFvCO8z6NWeRcA-ybnR55Ss"
ADMIN_IDS = [8504186560]
USDT_ADDRESS = "ТВОЙ_USDT_TRC20"
BOT_USERNAME = "FrpPortSaller_bot"
OWN_PROXY_SERVERS = []
HEALTH_CHECK_PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", f"http://localhost:{HEALTH_CHECK_PORT}")
# ===================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()

conn = sqlite3.connect('shop.db', check_same_thread=False)
c = conn.cursor()

c.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0,
        proxies TEXT, proxy_login TEXT, proxy_password TEXT,
        proxy_type TEXT, proxy_country TEXT, expiry TEXT,
        discount INTEGER DEFAULT 0, total_spent REAL DEFAULT 0,
        registered TEXT, banned INTEGER DEFAULT 0,
        language TEXT DEFAULT 'ru', auto_renew INTEGER DEFAULT 0,
        api_key TEXT, ref_code TEXT, level INTEGER DEFAULT 1,
        xp INTEGER DEFAULT 0, achievements TEXT DEFAULT '[]'
    );
    CREATE TABLE IF NOT EXISTS proxies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip TEXT, port TEXT, type TEXT, login TEXT, password TEXT,
        country TEXT, status TEXT, sold INTEGER DEFAULT 0,
        tier TEXT DEFAULT 'base', speed REAL DEFAULT 0,
        uptime REAL DEFAULT 100.0, last_check TEXT, added TEXT,
        source TEXT DEFAULT 'public', purpose TEXT DEFAULT 'all'
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER, referred_id INTEGER,
        level INTEGER DEFAULT 1, amount REAL DEFAULT 20, date TEXT
    );
    CREATE TABLE IF NOT EXISTS promocodes (
        code TEXT PRIMARY KEY, discount INTEGER, uses INTEGER,
        max_uses INTEGER, created_by INTEGER, created TEXT
    );
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, amount REAL, currency TEXT,
        status TEXT, date TEXT, payload TEXT, payment_method TEXT
    );
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, message TEXT, reply TEXT,
        status TEXT DEFAULT 'open', created TEXT, closed TEXT
    );
    CREATE TABLE IF NOT EXISTS achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, achievement TEXT, date TEXT
    );
''')
conn.commit()

PROXY_TIERS = {
    "base": {"price": 50, "name": "👤 Базовый", "icon": "🟢", "speed": "до 10 Мбит/с", "anon": "HTTP", "color": "#4CAF50", "purpose": "Сёрфинг, чтение"},
    "anon": {"price": 150, "name": "🕵️ Анонимный", "icon": "🟡", "speed": "до 50 Мбит/с", "anon": "HTTP(S)", "color": "#FF9800", "purpose": "Соцсети, парсинг"},
    "elite": {"price": 300, "name": "👑 Elite", "icon": "🔴", "speed": "до 100 Мбит/с", "anon": "SOCKS5", "color": "#F44336", "purpose": "Игры, стриминг, всё"},
}

PACKAGES = {
    "5": {"count": 5, "discount": 15, "name": "5 прокси"},
    "10": {"count": 10, "discount": 25, "name": "10 прокси"},
    "50": {"count": 50, "discount": 40, "name": "50 прокси"},
}

DURATIONS = {
    1: {"name": "1 день", "mult": 0, "badge": "🎁"},
    7: {"name": "1 неделя", "mult": 1, "badge": "📅"},
    14: {"name": "2 недели", "mult": 1.8, "badge": "📅"},
    30: {"name": "1 месяц", "mult": 3.5, "badge": "🔥"},
    90: {"name": "3 месяца", "mult": 9, "badge": "💎"},
    365: {"name": "1 год", "mult": 30, "badge": "👑"},
}

COUNTRIES = {"auto": "🌍 Авто", "ru": "🇷🇺 Россия", "us": "🇺🇸 США", "de": "🇩🇪 Германия", "nl": "🇳🇱 Нидерланды", "fr": "🇫🇷 Франция", "gb": "🇬🇧 Великобритания", "ua": "🇺🇦 Украина"}

PURPOSES = {"all": "Всё", "social": "Соцсети", "parsing": "Парсинг", "gaming": "Игры", "streaming": "Стриминг"}

FORMATS = {"ip_port": "IP:Port", "ip_port_user_pass": "IP:Port:Login:Pass", "full": "Полный конфиг", "dolphin": "Dolphin Anty", "ads": "AdsPower"}

LANGUAGES = {"ru": "🇷🇺 Русский", "en": "🇬🇧 English", "de": "🇩🇪 Deutsch", "uk": "🇺🇦 Українська"}

ACHIEVEMENTS_LIST = {
    "first_buy": {"name": "🎯 Первая покупка", "xp": 50},
    "ten_buys": {"name": "💎 10 покупок", "xp": 200},
    "hundred_days": {"name": "🏆 100 дней с прокси", "xp": 500},
    "five_refs": {"name": "👥 5 рефералов", "xp": 300},
    "elite_user": {"name": "👑 Elite пользователь", "xp": 1000},
}

class AdminStates(StatesGroup):
    waiting_mass_text = State()
    waiting_promo_discount = State()
    waiting_promo_uses = State()
    waiting_ticket_reply = State()
    waiting_add_balance_user = State()
    waiting_add_balance_amount = State()

class UserStates(StatesGroup):
    waiting_ticket_text = State()
    waiting_promo_input = State()
    waiting_withdraw_amount = State()
    waiting_language = State()

def generate_proxy_credentials():
    login = 'user_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    password = ''.join(random.choices(string.ascii_letters + string.digits + "!@#$%^&*", k=16))
    return login, password

def add_xp(user_id, amount):
    c.execute("UPDATE users SET xp=xp+? WHERE id=?", (amount, user_id))
    c.execute("SELECT xp FROM users WHERE id=?", (user_id,))
    xp = c.fetchone()[0]
    new_level = min(10, (xp // 200) + 1)
    c.execute("UPDATE users SET level=? WHERE id=?", (new_level, user_id))
    conn.commit()
    return new_level

def check_achievement(user_id, ach_id):
    c.execute("SELECT id FROM achievements WHERE user_id=? AND achievement=?", (user_id, ach_id))
    if not c.fetchone():
        c.execute("INSERT INTO achievements (user_id, achievement, date) VALUES (?, ?, ?)",
                  (user_id, ach_id, datetime.now().isoformat()))
        conn.commit()
        return True
    return False

async def fetch_proxies():
    sources = ['https://free-proxy-list.net/', 'https://www.sslproxies.org/', 'https://www.us-proxy.org/', 'https://www.socks-proxy.net/']
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
                            ptype = 'SOCKS5' if 'socks' in url else ('HTTPS' if 'yes' in cols[6].text.lower() else 'HTTP')
                            proxies.append({'ip': cols[0].text.strip(), 'port': cols[1].text.strip(), 'type': ptype, 'country': cols[3].text.strip() if len(cols) > 3 else 'Unknown'})
            except: pass
    return proxies

async def check_proxy_with_auth(ip, port, login="", password="", proxy_type='HTTP'):
    try:
        proxy_url = f'{proxy_type.lower()}://{login}:{password}@{ip}:{port}' if login else f'{proxy_type.lower()}://{ip}:{port}'
        async with aiohttp.ClientSession() as session:
            start = asyncio.get_event_loop().time()
            async with session.get('http://httpbin.org/ip', proxy=proxy_url, timeout=8) as resp:
                data = await resp.json()
                speed = round((asyncio.get_event_loop().time() - start) * 1000)
                if resp.status == 200: return True, speed, data.get('origin', '')
    except: pass
    return False, 0, ''

async def update_proxy_pool():
    while True:
        try:
            proxies = await fetch_proxies()
            added = 0
            for p in proxies[:50]:
                c.execute("SELECT id FROM proxies WHERE ip=? AND port=?", (p['ip'], p['port']))
                if not c.fetchone():
                    is_working, speed, _ = await check_proxy_with_auth(p['ip'], p['port'], proxy_type=p['type'])
                    if is_working:
                        login, password = generate_proxy_credentials()
                        tier = 'elite' if speed < 500 else ('anon' if speed < 1000 else 'base')
                        purposes = ['all', 'social', 'parsing'] if tier != 'elite' else ['all', 'social', 'parsing', 'gaming', 'streaming']
                        c.execute("INSERT INTO proxies (ip, port, type, login, password, country, status, tier, speed, uptime, last_check, added, source, purpose) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, 100.0, ?, ?, 'public', ?)",
                                  (p['ip'], p['port'], p['type'], login, password, p.get('country', 'Unknown'), tier, speed, datetime.now().isoformat(), datetime.now().isoformat(), random.choice(purposes)))
                        added += 1
            for own in OWN_PROXY_SERVERS:
                c.execute("SELECT id FROM proxies WHERE ip=? AND port=?", (own['ip'], str(own['port'])))
                if not c.fetchone():
                    c.execute("INSERT INTO proxies (ip, port, type, login, password, country, status, tier, speed, uptime, last_check, added, source, purpose) VALUES (?, ?, ?, ?, ?, 'Own', 'active', 'elite', 10, 100.0, ?, ?, 'own', 'all')",
                              (own['ip'], str(own['port']), own['type'], own['login'], own['password'], datetime.now().isoformat(), datetime.now().isoformat()))
                    added += 1
            conn.commit()
        except Exception as e: logger.error(f"Pool error: {e}")
        await asyncio.sleep(600)

async def monitor_and_notify():
    while True:
        try:
            now = datetime.now()
            c.execute("SELECT id, proxies, proxy_login, proxy_password, proxy_type, expiry FROM users WHERE proxies IS NOT NULL AND banned=0")
            for uid, proxy, login, pwd, ptype, expiry in c.fetchall():
                if not expiry or not proxy: continue
                try:
                    exp = datetime.fromisoformat(expiry)
                    hours_left = (exp - now).total_seconds() / 3600
                    if hours_left <= 0:
                        c.execute("UPDATE users SET proxies=NULL, proxy_login=NULL, proxy_password=NULL, expiry=NULL, auto_renew=0 WHERE id=?", (uid,))
                        conn.commit()
                        try: await bot.send_message(uid, "❌ Прокси истёк. /start для продления")
                        except: pass
                    elif 23 < hours_left <= 24:
                        try: await bot.send_message(uid, "⚠️ Прокси истекает через 24 часа!")
                        except: pass
                    if proxy and hours_left > 0:
                        ip, port = proxy.split(':')
                        is_working, speed, _ = await check_proxy_with_auth(ip, port, login or "", pwd or "", ptype or 'HTTP')
                        if not is_working:
                            await replace_user_proxy(uid)
                            try: await bot.send_message(uid, "🔄 Прокси заменён! Проверьте /start")
                            except: pass
                except: pass
        except Exception as e: logger.error(f"Monitor error: {e}")
        await asyncio.sleep(120)

async def replace_user_proxy(user_id):
    c.execute("SELECT * FROM proxies WHERE sold=0 AND status='active' ORDER BY speed ASC LIMIT 1")
    new_proxy = c.fetchone()
    if new_proxy:
        c.execute("UPDATE users SET proxies=?, proxy_login=?, proxy_password=?, proxy_type=? WHERE id=?",
                  (f"{new_proxy[1]}:{new_proxy[2]}", new_proxy[4], new_proxy[5], new_proxy[3], user_id))
        c.execute("UPDATE proxies SET sold=1 WHERE id=?", (new_proxy[0],))
        conn.commit()
        return True
    return False

def format_proxy_output(proxy_str, login, password, ptype, country, speed, expiry, fmt="full"):
    ip, port = proxy_str.split(':')
    country_name = COUNTRIES.get(country, country)
    if fmt == "ip_port": return f"{proxy_str}"
    elif fmt == "ip_port_user_pass": return f"{proxy_str}:{login}:{password}"
    elif fmt == "dolphin": return json.dumps({"proxy": {"type": ptype.lower(), "host": ip, "port": port, "login": login, "password": password}})
    elif fmt == "ads": return f"{ptype.lower()},{ip},{port},{login},{password}"
    else:
        speed_str = f"{speed} мс" if isinstance(speed, (int, float)) and speed > 0 else "проверяется..."
        exp_str = expiry.strftime('%d.%m.%Y %H:%M') if isinstance(expiry, datetime) else str(expiry)
        return (f"🔗 `{proxy_str}`\n👤 `{login}`\n🔑 `{password}`\n📡 {ptype}\n🌍 {country_name}\n⚡ {speed_str}\n📅 {exp_str}")

def get_setup_guide(proxy_str, login, password, proxy_type):
    ip, port = proxy_str.split(':')
    if proxy_type == 'SOCKS5':
        return f"📖 *SOCKS5:*\nХост: `{ip}` Порт: `{port}`\nЛогин: `{login}` Пароль: `{password}`"
    return f"📖 *{proxy_type}:*\nХост: `{ip}` Порт: `{port}`\nЛогин: `{login}` Пароль: `{password}`"

# ============ КЛАВИАТУРЫ ============
def main_menu(lang="ru"):
    texts = {
        "ru": ["🔓 Купить прокси", "📋 Мои прокси", "🔄 Проверить", "💰 Пополнить", "👥 Рефералы", "🏆 Достижения", "🌐 WebApp магазин", "📞 Поддержка"],
        "en": ["🔓 Buy proxy", "📋 My proxies", "🔄 Check", "💰 Top up", "👥 Referrals", "🏆 Achievements", "🌐 WebApp shop", "📞 Support"],
    }
    t = texts.get(lang, texts["ru"])
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=t[0], callback_data="buy_menu"))
    builder.row(InlineKeyboardButton(text=t[1], callback_data="my_proxies"), InlineKeyboardButton(text=t[2], callback_data="check_my_proxy"))
    builder.row(InlineKeyboardButton(text=t[3], callback_data="topup_menu"), InlineKeyboardButton(text=t[4], callback_data="ref_menu"))
    builder.row(InlineKeyboardButton(text=t[5], callback_data="achievements"), InlineKeyboardButton(text=t[6], web_app=WebAppInfo(url=f"{RENDER_URL}/app")))
    builder.row(InlineKeyboardButton(text=t[7], callback_data="support_menu"))
    return builder.as_markup()

def buy_menu_kb():
    builder = InlineKeyboardBuilder()
    for tid, tier in PROXY_TIERS.items():
        builder.row(InlineKeyboardButton(text=f"{tier['icon']} {tier['name']} — от {tier['price']}₽", callback_data=f"tier_{tid}"))
    builder.row(InlineKeyboardButton(text="📦 Пакеты прокси", callback_data="packages"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))
    return builder.as_markup()

def admin_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="👥 Пользователи")],
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="🎟 Промокоды")],
        [KeyboardButton(text="➕ Баланс юзеру"), KeyboardButton(text="📋 Тикеты")],
        [KeyboardButton(text="📤 Экспорт БД"), KeyboardButton(text="🔄 Обновить пул")],
        [KeyboardButton(text="🔙 Выход из админки")],
    ], resize_keyboard=True)

# ============ WebApp HTML ============
WEBAPP_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <title>RING PROXY</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--tg-theme-bg-color, #0f0f1a);
            color: var(--tg-theme-text-color, #fff);
            padding: 16px;
        }
        .header {
            text-align: center;
            padding: 24px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            border-radius: 20px;
            margin-bottom: 20px;
        }
        .header h1 { font-size: 26px; margin-bottom: 5px; }
        .header p { opacity: 0.85; font-size: 14px; }
        .card {
            background: var(--tg-theme-secondary-bg-color, #1a1a2e);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 12px;
            cursor: pointer;
            border: 2px solid transparent;
            transition: all 0.2s;
        }
        .card:hover { border-color: #667eea; }
        .card.selected { border-color: #667eea; background: rgba(102,126,234,0.1); }
        .card-header { display: flex; justify-content: space-between; align-items: center; }
        .card-title { font-size: 17px; font-weight: 600; }
        .card-price { font-size: 18px; font-weight: 700; color: #667eea; }
        .card-badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 11px;
            margin-top: 6px;
        }
        .row { display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0; }
        .chip {
            padding: 8px 14px;
            border-radius: 20px;
            background: var(--tg-theme-secondary-bg-color, #1a1a2e);
            cursor: pointer;
            font-size: 13px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .chip.selected { background: #667eea; border-color: #667eea; }
        .btn {
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: #fff;
            border: none;
            border-radius: 14px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 16px;
        }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .total {
            text-align: center;
            padding: 16px;
            background: rgba(102,126,234,0.1);
            border-radius: 14px;
            margin-top: 16px;
        }
        .total-price { font-size: 28px; font-weight: 700; color: #667eea; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🌐 RING PROXY</h1>
        <p>Выберите тариф и срок</p>
    </div>

    <div id="tiers"></div>

    <div class="section-title">🌍 Страна</div>
    <div class="row" id="countries"></div>

    <div class="section-title">📅 Срок</div>
    <div class="row" id="durations"></div>

    <div class="section-title">🎯 Цель</div>
    <div class="row" id="purposes"></div>

    <div class="total" id="totalBlock" style="display:none;">
        <div style="opacity:0.7;">Итого</div>
        <div class="total-price" id="totalPrice">0₽</div>
    </div>

    <button class="btn" id="buyBtn" disabled>Купить</button>

    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();

        const tiers = """ + json.dumps({k: {"name": v["name"], "price": v["price"], "icon": v["icon"], "color": v["color"]} for k, v in PROXY_TIERS.items()}) + """;
        const durations = """ + json.dumps({str(k): {"name": v["name"], "mult": v["mult"], "badge": v["badge"]} for k, v in DURATIONS.items()}) + """;
        const countries = """ + json.dumps(COUNTRIES) + """;
        const purposes = """ + json.dumps(PURPOSES) + """;

        let selected = { tier: null, country: 'auto', duration: null, purpose: 'all' };

        function renderTiers() {
            const div = document.getElementById('tiers');
            div.innerHTML = Object.entries(tiers).map(([id, t]) => `
                <div class="card ${selected.tier === id ? 'selected' : ''}" onclick="select('tier', '${id}')">
                    <div class="card-header">
                        <span class="card-title">${t.icon} ${t.name}</span>
                        <span class="card-price">от ${t.price}₽</span>
                    </div>
                    <span class="card-badge" style="background:${t.color}20;color:${t.color}">⚡ Высокая скорость</span>
                </div>
            `).join('');
        }

        function renderChips(container, data, key) {
            const div = document.getElementById(container);
            div.innerHTML = Object.entries(data).map(([id, val]) => `
                <span class="chip ${selected[key] == id ? 'selected' : ''}" onclick="select('${key}', '${id}')">
                    ${typeof val === 'object' ? (val.badge || '') + ' ' + val.name : val}
                </span>
            `).join('');
        }

        function select(type, value) {
            selected[type] = value;
            renderAll();
            updateTotal();
        }

        function renderAll() {
            renderTiers();
            renderChips('countries', countries, 'country');
            renderChips('durations', durations, 'duration');
            renderChips('purposes', purposes, 'purpose');
        }

        function updateTotal() {
            const block = document.getElementById('totalBlock');
            const btn = document.getElementById('buyBtn');
            if (selected.tier && selected.duration) {
                block.style.display = 'block';
                const t = tiers[selected.tier];
                const d = durations[selected.duration];
                const price = Math.round(t.price * d.mult);
                document.getElementById('totalPrice').textContent = d.mult === 0 ? 'БЕСПЛАТНО 🎁' : price + '₽';
                btn.disabled = false;
                btn.textContent = d.mult === 0 ? '🎁 Активировать бесплатно' : '💳 Оплатить ' + price + '₽';
            } else {
                block.style.display = 'none';
                btn.disabled = true;
                btn.textContent = 'Выберите тариф и срок';
            }
        }

        document.getElementById('buyBtn').addEventListener('click', () => {
            if (selected.tier && selected.duration) {
                tg.sendData(JSON.stringify(selected));
                tg.close();
            }
        });

        renderAll();

        tg.onEvent('mainButtonClicked', () => {
            if (selected.tier && selected.duration) {
                tg.sendData(JSON.stringify(selected));
                tg.close();
            }
        });
    </script>
</body>
</html>
"""

async def handle_webapp(request):
    return web.Response(text=WEBAPP_HTML, content_type='text/html')

async def health_check(request):
    return web.Response(text="OK")

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/app', handle_webapp)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HEALTH_CHECK_PORT)
    await site.start()
    logger.info(f"WebApp server on port {HEALTH_CHECK_PORT}")

# ============ ОБРАБОТЧИКИ ============
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    username = message.from_user.username
    c.execute("SELECT id, banned, language FROM users WHERE id=?", (uid,))
    user = c.fetchone()
    lang = user[2] if user else 'ru'
    if user and user[1] == 1:
        await message.answer("❌ Вы заблокированы.")
        return
    if not user:
        ref_code = hashlib.md5(str(uid).encode()).hexdigest()[:10]
        api_key = 'api_' + hashlib.md5(str(uid + random.randint(1, 9999)).encode()).hexdigest()[:16]
        c.execute("INSERT INTO users (id, username, balance, registered, ref_code, api_key) VALUES (?, ?, 10, ?, ?, ?)",
                  (uid, username, datetime.now().isoformat(), ref_code, api_key))
        conn.commit()
        args = message.text.split()
        if len(args) > 1 and args[1].startswith("ref_"):
            ref_hash = args[1][4:]
            c.execute("SELECT id FROM users WHERE ref_code=? AND id!=?", (ref_hash, uid))
            referrer = c.fetchone()
            if referrer:
                c.execute("INSERT INTO referrals (referrer_id, referred_id, level, amount, date) VALUES (?, ?, 1, 20, ?)",
                          (referrer[0], uid, datetime.now().isoformat()))
                c.execute("UPDATE users SET balance=balance+20 WHERE id=?", (referrer[0],))
                c.execute("SELECT referrer_id FROM referrals WHERE referred_id=? AND level=1", (referrer[0],))
                l2 = c.fetchone()
                if l2:
                    c.execute("INSERT INTO referrals (referrer_id, referred_id, level, amount, date) VALUES (?, ?, 2, 10, ?)",
                              (l2[0], uid, datetime.now().isoformat()))
                    c.execute("UPDATE users SET balance=balance+10 WHERE id=?", (l2[0],))
                conn.commit()
    await message.answer(
        "🌐 *RING PROXY BOT*\n\n"
        "🚀 Премиум прокси\n💳 Stars, USDT\n🔄 Автозамена\n🌐 WebApp\n👥 Рефералы 2 ур.\n🏆 Достижения\n📦 Пакеты прокси\n\n"
        "💰 Бонус 10₽ | 🎁 1 день бесплатно",
        parse_mode="Markdown", reply_markup=main_menu(lang)
    )

@dp.message(Command("proxy"))
async def cmd_proxy(message: Message):
    c.execute("SELECT proxies, proxy_login, proxy_password, proxy_type, proxy_country, expiry FROM users WHERE id=?", (message.from_user.id,))
    u = c.fetchone()
    if u and u[0]:
        exp = datetime.fromisoformat(u[5])
        output = format_proxy_output(u[0], u[1], u[2], u[3], u[4], 0, exp)
        await message.answer(f"📋 Ваш прокси:\n\n{output}", parse_mode="Markdown")
    else:
        await message.answer("Нет активного прокси. /start")

@dp.message(Command("check"))
async def cmd_check(message: Message):
    c.execute("SELECT proxies, proxy_login, proxy_password, proxy_type FROM users WHERE id=?", (message.from_user.id,))
    u = c.fetchone()
    if not u or not u[0]:
        await message.answer("Нет активного прокси."); return
    ip, port = u[0].split(':')
    await message.answer("🔄 Проверяю...")
    is_working, speed, origin = await check_proxy_with_auth(ip, port, u[1] or "", u[2] or "", u[3] or 'HTTP')
    if is_working:
        await message.answer(f"✅ Работает!\n⚡ {speed} мс\n🌐 `{origin}`", parse_mode="Markdown")
    else:
        await message.answer("❌ Не работает. Заменяю...")
        if await replace_user_proxy(message.from_user.id):
            await cmd_proxy(message)
        else:
            await message.answer("Нет свободных прокси.")

@dp.message(Command("renew"))
async def cmd_renew(message: Message):
    await message.answer("🔄 Нажмите /start → Купить прокси → выберите тариф", reply_markup=main_menu())

@dp.message(Command("api"))
async def cmd_api(message: Message):
    c.execute("SELECT api_key FROM users WHERE id=?", (message.from_user.id,))
    u = c.fetchone()
    await message.answer(f"🔑 API ключ:\n`{u[0]}`\n\nИспользуйте для автоматизации.", parse_mode="Markdown")

@dp.callback_query(F.data == "main_menu")
async def back_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🌐 *RING PROXY BOT*", parse_mode="Markdown", reply_markup=main_menu())

@dp.callback_query(F.data == "buy_menu")
async def show_buy_menu(callback: types.CallbackQuery):
    await callback.message.edit_text("🔓 *Выберите тариф или пакет:*", parse_mode="Markdown", reply_markup=buy_menu_kb())

@dp.callback_query(F.data == "packages")
async def show_packages(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for pid, pkg in PACKAGES.items():
        builder.row(InlineKeyboardButton(text=f"📦 {pkg['name']} — скидка {pkg['discount']}%", callback_data=f"package_{pid}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="buy_menu"))
    await callback.message.edit_text("📦 *Пакеты прокси:*\n\n5 прокси — 15%\n10 прокси — 25%\n50 прокси — 40%", parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("tier_"))
async def show_tier(callback: types.CallbackQuery):
    tid = callback.data.split("_")[1]
    tier = PROXY_TIERS[tid]
    builder = InlineKeyboardBuilder()
    for cid, cname in COUNTRIES.items():
        builder.row(InlineKeyboardButton(text=cname, callback_data=f"durations_{tid}_{cid}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="buy_menu"))
    await callback.message.edit_text(f"{tier['icon']} *{tier['name']}*\n⚡ {tier['speed']}\n🔒 {tier['anon']}\n🎯 {tier['purpose']}\n\n🌍 Выберите страну:", parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("durations_"))
async def show_durations(callback: types.CallbackQuery):
    _, tid, country = callback.data.split("_")
    builder = InlineKeyboardBuilder()
    for days, info in DURATIONS.items():
        if days == 1:
            label = f"{info['badge']} {info['name']} — БЕСПЛАТНО"
        else:
            price = int(PROXY_TIERS[tid]['price'] * info['mult'])
            label = f"{info['badge']} {info['name']} — {price}₽"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"buy_{tid}_{days}_{country}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"tier_{tid}"))
    await callback.message.edit_text(f"{PROXY_TIERS[tid]['icon']} {PROXY_TIERS[tid]['name']}\n{COUNTRIES.get(country, 'Авто')}\n📅 Срок:", parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def confirm_buy(callback: types.CallbackQuery):
    _, tid, days, country = callback.data.split("_")
    days = int(days)
    tier = PROXY_TIERS[tid]
    dur = DURATIONS[days]
    if days == 1: final = 0
    else:
        price = int(tier['price'] * dur['mult'])
        c.execute("SELECT discount FROM users WHERE id=?", (callback.from_user.id,))
        disc = c.fetchone()[0] or 0
        final = int(price * (1 - disc/100))
    builder = InlineKeyboardBuilder()
    if final == 0:
        builder.row(InlineKeyboardButton(text="🎁 Активировать бесплатно", callback_data=f"activate_free_{tid}_{country}"))
    else:
        builder.row(InlineKeyboardButton(text=f"⭐ Stars ({final}⭐)", callback_data=f"paystars_{tid}_{days}_{country}_{final}"))
        builder.row(InlineKeyboardButton(text="💎 USDT TRC20", callback_data=f"payusdt_{tid}_{days}_{country}_{price}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"durations_{tid}_{country}"))
    await callback.message.edit_text(
        f"🛒 *{tier['name']}*\n🌍 {COUNTRIES.get(country, 'Авто')}\n📅 {dur['name']}\n💰 {'Бесплатно' if final == 0 else f'{final}₽'}",
        parse_mode="Markdown", reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("activate_free_"))
async def activate_free(callback: types.CallbackQuery):
    _, _, tid, country = callback.data.split("_")
    c.execute("SELECT id FROM payments WHERE user_id=? AND payload LIKE '%trial%'", (callback.from_user.id,))
    if c.fetchone():
        await callback.answer("❌ Пробный период уже использован!", show_alert=True); return
    result = await activate_proxy(callback.from_user.id, tid, 1, country, 0, 'FREE', 'trial')
    if result:
        check_achievement(callback.from_user.id, "first_buy")
        add_xp(callback.from_user.id, ACHIEVEMENTS_LIST["first_buy"]["xp"])
        await show_proxy_info(callback.from_user.id, callback.message)
    else:
        await callback.message.edit_text("❌ Нет доступных прокси.", reply_markup=main_menu())

async def activate_proxy(uid, tid, days, country, amount, currency, payment_type=''):
    c.execute("SELECT * FROM proxies WHERE sold=0 AND status='active' AND tier=? ORDER BY speed ASC LIMIT 1", (tid,))
    proxy = c.fetchone()
    if not proxy:
        c.execute("SELECT * FROM proxies WHERE sold=0 AND status='active' ORDER BY speed ASC LIMIT 1")
        proxy = c.fetchone()
    if proxy:
        proxy_str = f"{proxy[1]}:{proxy[2]}"
        expiry = datetime.now() + timedelta(days=days)
        c.execute("UPDATE proxies SET sold=1 WHERE id=?", (proxy[0],))
        c.execute("UPDATE users SET proxies=?, proxy_login=?, proxy_password=?, proxy_type=?, proxy_country=?, expiry=?, discount=0, total_spent=total_spent+? WHERE id=?",
                  (proxy_str, proxy[4], proxy[5], proxy[3], country, expiry.isoformat(), amount, uid))
        c.execute("INSERT INTO payments (user_id, amount, currency, status, date, payload, payment_method) VALUES (?, ?, ?, 'success', ?, ?, ?)",
                  (uid, amount, currency, datetime.now().isoformat(), f"{tid}_{days}_{country}_{payment_type}", payment_type or currency))
        if amount > 0:
            c.execute("SELECT referrer_id FROM referrals WHERE referred_id=? AND level=1", (uid,))
            ref1 = c.fetchone()
            if ref1:
                bonus1 = int(amount * 0.3)
                c.execute("UPDATE users SET balance=balance+? WHERE id=?", (bonus1, ref1[0]))
                c.execute("UPDATE referrals SET amount=amount+? WHERE referred_id=?", (bonus1, uid))
                try: await bot.send_message(ref1[0], f"🎉 Реферал купил прокси! +{bonus1}₽")
                except: pass
                c.execute("SELECT referrer_id FROM referrals WHERE referred_id=? AND level=2", (ref1[0],))
                ref2 = c.fetchone()
                if ref2:
                    bonus2 = int(amount * 0.1)
                    c.execute("UPDATE users SET balance=balance+? WHERE id=?", (bonus2, ref2[0]))
                    try: await bot.send_message(ref2[0], f"🎉 2 уровень реферала! +{bonus2}₽")
                    except: pass
        conn.commit()
        return proxy_str, proxy[4], proxy[5], proxy[3], proxy[7], expiry
    return None

async def show_proxy_info(user_id, message):
    c.execute("SELECT proxies, proxy_login, proxy_password, proxy_type, proxy_country, expiry FROM users WHERE id=?", (user_id,))
    u = c.fetchone()
    if not u or not u[0]:
        await message.answer("Нет активных прокси.", reply_markup=main_menu()); return
    proxy_str, login, pwd, ptype, country, expiry = u
    exp = datetime.fromisoformat(expiry)
    c.execute("SELECT speed FROM proxies WHERE ip=? AND port=?", (proxy_str.split(':')[0], proxy_str.split(':')[1]))
    sp = c.fetchone()
    speed = sp[0] if sp and sp[0] and sp[0] > 0 else "проверяется..."
    output = format_proxy_output(proxy_str, login, pwd, ptype, country, speed, exp, "full")
    guide = get_setup_guide(proxy_str, login, pwd, ptype)
    builder = InlineKeyboardBuilder()
    for fid, fname in FORMATS.items():
        builder.row(InlineKeyboardButton(text=f"📋 {fname}", callback_data=f"exportfmt_{fid}"))
    builder.row(InlineKeyboardButton(text="📋 Скопировать IP:Port", callback_data=f"copy_{proxy_str}"))
    builder.row(InlineKeyboardButton(text="🔄 Проверить", callback_data="check_my_proxy"))
    builder.row(InlineKeyboardButton(text="🔙 Меню", callback_data="main_menu"))
    await message.answer(f"✅ *Прокси активирован!*\n\n{output}\n\n{guide}", parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("copy_"))
async def copy_proxy(callback: types.CallbackQuery):
    proxy = callback.data.split("_", 1)[1]
    await callback.message.answer(f"`{proxy}`", parse_mode="Markdown")
    await callback.answer("✅ Скопируйте выше", show_alert=True)

@dp.callback_query(F.data.startswith("exportfmt_"))
async def export_format(callback: types.CallbackQuery):
    fmt = callback.data.split("_")[1]
    c.execute("SELECT proxies, proxy_login, proxy_password, proxy_type, proxy_country, expiry FROM users WHERE id=?", (callback.from_user.id,))
    u = c.fetchone()
    if u and u[0]:
        exp = datetime.fromisoformat(u[5])
        c.execute("SELECT speed FROM proxies WHERE ip=? AND port=?", (u[0].split(':')[0], u[0].split(':')[1]))
        sp = c.fetchone()
        speed = sp[0] if sp else 0
        output = format_proxy_output(u[0], u[1], u[2], u[3], u[4], speed, exp, fmt)
        await callback.message.answer(f"```\n{output}\n```", parse_mode="Markdown")
    else:
        await callback.answer("Нет активного прокси", show_alert=True)

@dp.callback_query(F.data.startswith("paystars_"))
async def pay_stars(callback: types.CallbackQuery):
    _, tid, days, country, final = callback.data.split("_")
    await callback.message.answer_invoice(
        title=f"Прокси {PROXY_TIERS[tid]['name']}",
        description=f"{DURATIONS[int(days)]['name']} | {COUNTRIES.get(country, '')}",
        payload=f"proxy_{tid}_{days}_{country}",
        provider_token="", currency="XTR",
        prices=[LabeledPrice(label=DURATIONS[int(days)]['name'], amount=int(final))],
        need_name=False, need_phone_number=False, need_email=False,
    )
    await callback.message.edit_text("✅ Счёт выставлен", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Меню", callback_data="main_menu")]
    ]))

@dp.message(F.successful_payment)
async def on_payment(message: Message):
    _, tid, days, country = message.successful_payment.invoice_payload.split("_")
    days = int(days)
    await activate_proxy(message.from_user.id, tid, days, country, message.successful_payment.total_amount, 'XTR', 'stars')
    c.execute("SELECT COUNT(*) FROM payments WHERE user_id=? AND status='success'", (message.from_user.id,))
    buy_count = c.fetchone()[0]
    if buy_count >= 10:
        if check_achievement(message.from_user.id, "ten_buys"):
            add_xp(message.from_user.id, ACHIEVEMENTS_LIST["ten_buys"]["xp"])
            await message.answer("🏆 Достижение: *10 покупок!* +200 XP", parse_mode="Markdown")
    await show_proxy_info(message.from_user.id, message)

@dp.callback_query(F.data == "my_proxies")
async def my_proxies(callback: types.CallbackQuery):
    await show_proxy_info(callback.from_user.id, callback.message)

@dp.callback_query(F.data == "check_my_proxy")
async def check_my_proxy(callback: types.CallbackQuery):
    c.execute("SELECT proxies, proxy_login, proxy_password, proxy_type FROM users WHERE id=?", (callback.from_user.id,))
    u = c.fetchone()
    if not u or not u[0]:
        await callback.answer("❌ Нет активного прокси", show_alert=True); return
    await callback.answer("🔄 Проверяю...")
    ip, port = u[0].split(':')
    is_working, speed, origin = await check_proxy_with_auth(ip, port, u[1] or "", u[2] or "", u[3] or 'HTTP')
    if is_working:
        c.execute("UPDATE proxies SET speed=?, last_check=? WHERE ip=? AND port=?", (speed, datetime.now().isoformat(), ip, port))
        conn.commit()
        await callback.message.answer(f"✅ *Работает!*\n⚡ {speed} мс\n🌐 `{origin}`", parse_mode="Markdown")
    else:
        await callback.message.answer("❌ Не работает. Заменяю...")
        if await replace_user_proxy(callback.from_user.id):
            await show_proxy_info(callback.from_user.id, callback.message)
        else:
            await callback.message.answer("Нет свободных прокси.", reply_markup=main_menu())

@dp.callback_query(F.data == "topup_menu")
async def topup_menu(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⭐ Stars", callback_data="topup_stars"))
    builder.row(InlineKeyboardButton(text="💎 USDT TRC20", callback_data="topup_usdt"))
    builder.row(InlineKeyboardButton(text="💳 Карты (скоро)", callback_data="topup_soon"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))
    await callback.message.edit_text("💰 *Пополнение*", parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "topup_soon")
async def topup_soon(callback: types.CallbackQuery):
    await callback.answer("💳 Оплата картами, гривнами, рублями, долларами, евро — скоро!", show_alert=True)

@dp.callback_query(F.data == "ref_menu")
async def ref_menu(callback: types.CallbackQuery):
    c.execute("SELECT ref_code, balance FROM users WHERE id=?", (callback.from_user.id,))
    u = c.fetchone()
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{u[0]}" if u else "Ошибка"
    c.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM referrals WHERE referrer_id=?", (callback.from_user.id,))
    cnt, total = c.fetchone()
    await callback.message.edit_text(
        f"👥 *Рефералы 2 уровня*\n\n🔗 `{ref_link}`\n\n👤 {cnt or 0}\n💰 {total or 0}₽\n💎 Баланс: {u[1]}₽\n\n• 1 ур: +20₽ + 30%\n• 2 ур: +10₽ + 10%",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=ref_link)],
            [InlineKeyboardButton(text="💸 Вывести", callback_data="withdraw")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
        ])
    )

@dp.callback_query(F.data == "withdraw")
async def withdraw_start(callback: types.CallbackQuery, state: FSMContext):
    c.execute("SELECT balance FROM users WHERE id=?", (callback.from_user.id,))
    bal = c.fetchone()[0]
    if bal < 500:
        await callback.answer("❌ Минимальная сумма вывода: 500₽", show_alert=True); return
    await state.set_state(UserStates.waiting_withdraw_amount)
    await callback.message.answer(f"💰 Баланс: {bal}₽\nВведите сумму для вывода (мин. 500₽):")

@dp.message(UserStates.waiting_withdraw_amount)
async def withdraw_amount(message: Message, state: FSMContext):
    try:
        amt = float(message.text)
        c.execute("SELECT balance FROM users WHERE id=?", (message.from_user.id,))
        bal = c.fetchone()[0]
        if amt < 500 or amt > bal:
            await message.answer("❌ Сумма должна быть от 500₽ до вашего баланса"); return
        c.execute("UPDATE users SET balance=balance-? WHERE id=?", (amt, message.from_user.id))
        conn.commit()
        for aid in ADMIN_IDS:
            await bot.send_message(aid, f"💸 Заявка на вывод от @{message.from_user.username}: {amt}₽")
        await message.answer(f"✅ Заявка на {amt}₽ отправлена! Админ свяжется с вами.", reply_markup=main_menu())
    except:
        await message.answer("❌ Введите число")
    await state.clear()

@dp.callback_query(F.data == "achievements")
async def show_achievements(callback: types.CallbackQuery):
    c.execute("SELECT xp, level FROM users WHERE id=?", (callback.from_user.id,))
    u = c.fetchone()
    xp, lvl = u if u else (0, 1)
    c.execute("SELECT achievement, date FROM achievements WHERE user_id=? ORDER BY date DESC", (callback.from_user.id,))
    achs = c.fetchall()
    ach_text = "\n".join([f"{ACHIEVEMENTS_LIST.get(a[0], {}).get('name', a[0])} — {a[1][:10]}" for a in achs]) if achs else "Нет достижений"
    await callback.message.edit_text(
        f"🏆 *Достижения*\n\n⭐ Уровень: {lvl}\n✨ XP: {xp}/{(lvl)*200}\n\n{ach_text}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ])
    )

@dp.callback_query(F.data == "promo_enter")
async def promo_enter(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_promo_input)
    await callback.message.edit_text("🎟 Введите промокод:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="main_menu")]
    ]))

@dp.message(UserStates.waiting_promo_input)
async def apply_promo(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    c.execute("SELECT discount, uses FROM promocodes WHERE code=? AND uses>0", (code,))
    promo = c.fetchone()
    if not promo:
        await message.answer("❌ Недействителен"); await state.clear(); return
    c.execute("UPDATE promocodes SET uses=uses-1 WHERE code=?", (code,))
    c.execute("UPDATE users SET discount=? WHERE id=?", (promo[0], message.from_user.id))
    conn.commit()
    await message.answer(f"✅ Скидка {promo[0]}%!", reply_markup=main_menu())
    await state.clear()

@dp.callback_query(F.data == "support_menu")
async def support_menu(callback: types.CallbackQuery):
    await callback.message.edit_text("📞 Опишите проблему:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать", callback_data="new_ticket")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")],
    ]))

@dp.callback_query(F.data == "new_ticket")
async def new_ticket(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_ticket_text)
    await callback.message.answer("Опишите проблему:")

@dp.message(UserStates.waiting_ticket_text)
async def save_ticket(message: Message, state: FSMContext):
    c.execute("INSERT INTO tickets (user_id, username, message, created) VALUES (?, ?, ?, ?)",
              (message.from_user.id, message.from_user.username, message.text, datetime.now().isoformat()))
    conn.commit()
    for aid in ADMIN_IDS:
        try: await bot.send_message(aid, f"📋 Тикет #{c.lastrowid}")
        except: pass
    await message.answer("✅ Принято!", reply_markup=main_menu())
    await state.clear()

# ============ АДМИНКА ============
@dp.message(F.text == "/admin")
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    await message.answer("🔐 *Админ-панель*", parse_mode="Markdown", reply_markup=admin_kb())

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    c.execute("SELECT COUNT(*) FROM users"); tu = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE proxies IS NOT NULL"); au = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='success'"); rev = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM proxies WHERE sold=0 AND status='active'"); av = c.fetchone()[0]
    await message.answer(f"📊 *Статистика*\n👥 {tu}\n🟢 {au}\n🛒 {av}\n💰 {rev} Stars", parse_mode="Markdown")

@dp.message(F.text == "🔄 Обновить пул")
async def force_update(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    proxies = await fetch_proxies()
    added = 0
    for p in proxies[:20]:
        c.execute("SELECT id FROM proxies WHERE ip=? AND port=?", (p['ip'], p['port']))
        if not c.fetchone():
            is_working, speed, _ = await check_proxy_with_auth(p['ip'], p['port'], proxy_type=p['type'])
            if is_working:
                login, password = generate_proxy_credentials()
                c.execute("INSERT INTO proxies (ip, port, type, login, password, country, status, tier, speed, uptime, last_check, added, source, purpose) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, 100.0, ?, ?, 'public', 'all')",
                          (p['ip'], p['port'], p['type'], login, password, p.get('country', 'Unknown'), 'elite' if speed < 500 else ('anon' if speed < 1000 else 'base'), speed, datetime.now().isoformat(), datetime.now().isoformat()))
                added += 1
    conn.commit()
    await message.answer(f"✅ +{added} прокси")

@dp.message(F.text == "📢 Рассылка")
async def mass_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminStates.waiting_mass_text)
    await message.answer("Текст:")

@dp.message(AdminStates.waiting_mass_text)
async def mass_send(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    c.execute("SELECT id FROM users WHERE banned=0")
    sent = 0
    for (uid,) in c.fetchall():
        try: await bot.send_message(uid, message.text); sent += 1; await asyncio.sleep(0.05)
        except: pass
    await message.answer(f"✅ {sent}"); await state.clear()

@dp.message(F.text == "🎟 Промокоды")
async def promo_menu(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    c.execute("SELECT * FROM promocodes")
    codes = c.fetchall()
    text = "🎟 *Промокоды:*\n" + ("\n".join([f"`{x[0]}` — {x[1]}%, {x[2]}/{x[3]}" for x in codes]) if codes else "Нет")
    await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать", callback_data="create_promo")]
    ]))

@dp.callback_query(F.data == "create_promo")
async def create_promo_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_promo_discount)
    await callback.message.answer("Скидка %:")

@dp.message(AdminStates.waiting_promo_discount)
async def promo_discount(message: Message, state: FSMContext):
    try:
        await state.update_data(promo_discount=int(message.text))
        await state.set_state(AdminStates.waiting_promo_uses)
        await message.answer("Кол-во:")
    except: await message.answer("Число!")

@dp.message(AdminStates.waiting_promo_uses)
async def promo_uses(message: Message, state: FSMContext):
    try:
        uses = int(message.text)
        data = await state.get_data()
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        c.execute("INSERT INTO promocodes VALUES (?, ?, ?, ?, ?, ?)", (code, data['promo_discount'], uses, uses, message.from_user.id, datetime.now().isoformat()))
        conn.commit()
        await message.answer(f"✅ `{code}` — {data['promo_discount']}%, {uses}шт.", parse_mode="Markdown")
        await state.clear()
    except: await message.answer("Число!")

@dp.message(F.text == "➕ Баланс юзеру")
async def add_balance_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    await state.set_state(AdminStates.waiting_add_balance_user)
    await message.answer("ID:")

@dp.message(AdminStates.waiting_add_balance_user)
async def add_balance_user(message: Message, state: FSMContext):
    try:
        await state.update_data(uid=int(message.text))
        await state.set_state(AdminStates.waiting_add_balance_amount)
        await message.answer("Сумма:")
    except: await message.answer("Число!")

@dp.message(AdminStates.waiting_add_balance_amount)
async def add_balance_amount(message: Message, state: FSMContext):
    try:
        amt = float(message.text)
        data = await state.get_data()
        c.execute("UPDATE users SET balance=balance+? WHERE id=?", (amt, data['uid']))
        conn.commit()
        await message.answer(f"✅ +{amt}₽"); await state.clear()
    except: await message.answer("Число!")

@dp.message(F.text == "📋 Тикеты")
async def admin_tickets(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    c.execute("SELECT id, user_id, message FROM tickets WHERE status='open' LIMIT 10")
    for t in c.fetchall():
        await message.answer(f"📋 #{t[0]} | {t[1]}\n{t[2]}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"reply_ticket_{t[0]}")],
        ]))

@dp.callback_query(F.data.startswith("reply_ticket_"))
async def reply_ticket(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(tid=int(callback.data.split("_")[2]))
    await state.set_state(AdminStates.waiting_ticket_reply)
    await callback.message.answer("Ответ:")

@dp.message(AdminStates.waiting_ticket_reply)
async def reply_ticket_send(message: Message, state: FSMContext):
    data = await state.get_data()
    c.execute("SELECT user_id FROM tickets WHERE id=?", (data['tid'],))
    t = c.fetchone()
    if t:
        c.execute("UPDATE tickets SET reply=?, status='closed' WHERE id=?", (message.text, data['tid']))
        conn.commit()
        try: await bot.send_message(t[0], f"📞 Ответ:\n\n{message.text}")
        except: pass
    await message.answer("✅"); await state.clear()

@dp.message(F.text == "📤 Экспорт БД")
async def export_db(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "Users"
    for row in c.execute("SELECT * FROM users"): ws.append(list(row))
    output = BytesIO(); wb.save(output); output.seek(0)
    await message.answer_document(BufferedInputFile(output.read(), "export.xlsx"))

@dp.message(F.text == "🔙 Выход из админки")
async def exit_admin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Вышли", reply_markup=types.ReplyKeyboardRemove())

# ============ ЗАПУСК ============
async def main():
    logger.info("Starting RING PROXY BOT...")
    asyncio.create_task(update_proxy_pool())
    asyncio.create_task(monitor_and_notify())
    asyncio.create_task(run_web_server())
    logger.info("Bot started!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
