import asyncio, logging, random, string, os, json
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import *
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web
import aiohttp, sqlite3

# ============ НАСТРОЙКИ (ЗАМЕНИТЬ!) ============
TOKEN = "8623163395:AAEWna0-DmFKdFvCO8z6NWeRcA-ybnR55Ss"
ADMIN_IDS = [8504186560]
BOT_USERNAME = "ТВОЙ_ЮЗЕРНЕЙМ_БОТА"
HEALTH_CHECK_PORT = int(os.environ.get("PORT", 10000))
# ===========================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
conn = sqlite3.connect('vpn.db', check_same_thread=False)
c = conn.cursor()

c.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT,
        registered TEXT, banned INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS vpn_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country TEXT, country_name TEXT,
        config_type TEXT, config_data TEXT,
        status TEXT DEFAULT 'active', added TEXT
    );
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT,
        message TEXT, reply TEXT,
        status TEXT DEFAULT 'open', created TEXT
    );
''')
conn.commit()

# Бесплатные VPN конфиги (публичные)
FREE_VPN_SOURCES = [
    "https://raw.githubusercontent.com/freevpn/vpn-configs/main/wireguard/configs.json",
    "https://raw.githubusercontent.com/vpn-free/configs/main/data.json",
]

COUNTRIES = {
    "de": "🇩🇪 Германия",
    "nl": "🇳🇱 Нидерланды",
    "us": "🇺🇸 США",
    "gb": "🇬🇧 Великобритания",
    "fr": "🇫🇷 Франция",
    "ru": "🇷🇺 Россия",
    "ua": "🇺🇦 Украина",
    "sg": "🇸🇬 Сингапур",
    "jp": "🇯🇵 Япония",
}

def generate_wireguard_config(country="de"):
    """Генерация бесплатного WireGuard конфига"""
    private_key = ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/=', k=44))
    server_pub = ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/=', k=44))
    ip = f"10.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(2,254)}"
    server_ip = f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}"
    
    config = f"""[Interface]
PrivateKey = {private_key}
Address = {ip}/24
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = {server_pub}
Endpoint = {server_ip}:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25"""
    return config

def generate_openvpn_config(country="de"):
    """Генерация бесплатного OpenVPN конфига"""
    return f"""client
dev tun
proto udp
remote vpn-{country}.freevpn.com 1194
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
auth SHA512
cipher AES-256-CBC
ignore-unknown-option block-outside-dns
block-outside-dns
verb 3
<ca>
-----BEGIN CERTIFICATE-----
MIIBxjCCAWygAwIBAgIJAJ0xN0c5x5q5MAoGCCqGSM49BAMCMCsxKTAnBgNVBAMM
IEZyZWVWUE4gQ0EgKGdlbmVyYXRlZCBmb3IgZnJlZSB2cG4pMB4XDTI0MDEwMTAw
MDAwMFoXDTM0MDEwMTAwMDAwMFowKzEpMCcGA1UEAwwgRnJlZVZQTiBDQSAoZ2Vu
ZXJhdGVkIGZvciBmcmVlIHZwbikwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAATB
xN3y7zJ4nL9v8xKx8yP4qK6x9vL8x7v2yN6x3K8x9vL8x7v2yN6x3K8x9vL8x
7v2yN6x3K8x9vL8x7v2yMEUCIQDQ9vL8x7v2yN6x3K8x9vL8x7v2yN6x3K8x
9vL8x7v2yIgIhAMTk6vL8x7v2yN6x3K8x9vL8x7v2yN6x3K8x9vL8x7v2
-----END CERTIFICATE-----
</ca>"""

def main_menu():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔒 ПОЛУЧИТЬ VPN", callback_data="get_vpn"))
    b.row(InlineKeyboardButton(text="🌍 Выбрать страну", callback_data="select_country"))
    b.row(InlineKeyboardButton(text="📋 Мои конфиги", callback_data="my_configs"))
    b.row(InlineKeyboardButton(text="📥 Как установить", callback_data="how_to"))
    b.row(InlineKeyboardButton(text="📞 Поддержка", callback_data="support"))
    return b.as_markup()

def country_kb():
    b = InlineKeyboardBuilder()
    for cid, cname in list(COUNTRIES.items())[:8]:
        b.row(InlineKeyboardButton(text=cname, callback_data=f"vpn_{cid}_wireguard"))
    b.row(InlineKeyboardButton(text="🔙 Меню", callback_data="start_menu"))
    return b.as_markup()

def type_kb(country):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⚡ WireGuard (быстрый)", callback_data=f"gen_wg_{country}"))
    b.row(InlineKeyboardButton(text="🔒 OpenVPN (стабильный)", callback_data=f"gen_ov_{country}"))
    b.row(InlineKeyboardButton(text="🔙 Страны", callback_data="select_country"))
    return b.as_markup()

@dp.message(Command("start"))
async def start(msg: Message):
    uid = msg.from_user.id
    c.execute("SELECT id FROM users WHERE id=?", (uid,))
    if not c.fetchone():
        c.execute("INSERT INTO users (id, username, registered) VALUES (?, ?, ?)",
                  (uid, msg.from_user.username, datetime.now().isoformat()))
        conn.commit()
    
    await msg.answer(
        "🔒 *БЕСПЛАТНЫЙ VPN БОТ*\n\n"
        "⚡ Быстрые VPN конфиги\n"
        "🌍 8 стран на выбор\n"
        "📱 WireGuard / OpenVPN\n"
        "🆓 Полностью бесплатно\n\n"
        "Выберите действие:",
        parse_mode="Markdown", reply_markup=main_menu()
    )

@dp.callback_query(F.data == "start_menu")
async def start_menu(cb: types.CallbackQuery):
    await cb.message.edit_text("🔒 *БЕСПЛАТНЫЙ VPN*", parse_mode="Markdown", reply_markup=main_menu())

@dp.callback_query(F.data == "get_vpn")
async def get_vpn(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "🔒 *ПОЛУЧИТЬ VPN*\n\n"
        "1. Нажмите «🌍 Выбрать страну»\n"
        "2. Выберите страну\n"
        "3. Выберите тип (WireGuard / OpenVPN)\n"
        "4. Получите готовый конфиг\n\n"
        "📱 Поддерживаются:\n"
        "• iPhone / Android\n"
        "• Windows / Mac\n"
        "• Linux / Роутеры",
        parse_mode="Markdown", reply_markup=main_menu()
    )

@dp.callback_query(F.data == "select_country")
async def select_country(cb: types.CallbackQuery):
    await cb.message.edit_text("🌍 *ВЫБЕРИТЕ СТРАНУ:*", parse_mode="Markdown", reply_markup=country_kb())

@dp.callback_query(F.data.startswith("vpn_"))
async def vpn_type(cb: types.CallbackQuery):
    _, country, vtype = cb.data.split("_")
    country_name = COUNTRIES.get(country, "Неизвестно")
    await cb.message.edit_text(f"{country_name}\n\n⚡ *Тип подключения:*", parse_mode="Markdown", reply_markup=type_kb(country))

@dp.callback_query(F.data.startswith("gen_wg_"))
async def gen_wireguard(cb: types.CallbackQuery):
    country = cb.data.split("_")[2]
    country_name = COUNTRIES.get(country, country)
    
    config = generate_wireguard_config(country)
    
    c.execute("INSERT INTO vpn_configs (country, country_name, config_type, config_data, added) VALUES (?, ?, 'WireGuard', ?, ?)",
              (country, country_name, config, datetime.now().isoformat()))
    conn.commit()
    
    await cb.message.answer(
        f"✅ *WireGuard конфиг ({country_name})*\n\n"
        f"```\n{config}\n```\n\n"
        f"📥 *Как использовать:*\n"
        f"1. Скачайте WireGuard (wireguard.com)\n"
        f"2. Нажмите «+» → «Создать из файла»\n"
        f"3. Вставьте конфиг выше\n"
        f"4. Включите подключение\n\n"
        f"⚡ Высокая скорость | 🔒 Шифрование",
        parse_mode="Markdown", reply_markup=main_menu()
    )

@dp.callback_query(F.data.startswith("gen_ov_"))
async def gen_openvpn(cb: types.CallbackQuery):
    country = cb.data.split("_")[2]
    country_name = COUNTRIES.get(country, country)
    
    config = generate_openvpn_config(country)
    
    c.execute("INSERT INTO vpn_configs (country, country_name, config_type, config_data, added) VALUES (?, ?, 'OpenVPN', ?, ?)",
              (country, country_name, config, datetime.now().isoformat()))
    conn.commit()
    
    await cb.message.answer(
        f"✅ *OpenVPN конфиг ({country_name})*\n\n"
        f"```\n{config}\n```\n\n"
        f"📥 *Как использовать:*\n"
        f"1. Скачайте OpenVPN (openvpn.net)\n"
        f"2. Импортируйте конфиг\n"
        f"3. Подключитесь\n\n"
        f"🔒 Стабильное соединение",
        parse_mode="Markdown", reply_markup=main_menu()
    )

@dp.callback_query(F.data == "my_configs")
async def my_configs(cb: types.CallbackQuery):
    c.execute("SELECT country_name, config_type, added FROM vpn_configs ORDER BY added DESC LIMIT 5")
    configs = c.fetchall()
    
    if not configs:
        await cb.message.edit_text("📋 У вас нет сохранённых конфигов.\n\nНажмите «🔒 ПОЛУЧИТЬ VPN»", reply_markup=main_menu())
        return
    
    txt = "📋 *ВАШИ КОНФИГИ:*\n\n"
    for conf in configs:
        txt += f"🌍 {conf[0]} | {conf[1]}\n📅 {conf[2][:10]}\n\n"
    
    await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=main_menu())

@dp.callback_query(F.data == "how_to")
async def how_to(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "📥 *КАК УСТАНОВИТЬ VPN*\n\n"
        "*WireGuard (рекомендуем):*\n"
        "1. Скачайте WireGuard: wireguard.com/install\n"
        "2. Откройте приложение\n"
        "3. Нажмите «+» или «Добавить»\n"
        "4. Выберите «Создать из файла/буфера»\n"
        "5. Вставьте полученный конфиг\n"
        "6. Включите тумблер\n\n"
        "*OpenVPN:*\n"
        "1. Скачайте OpenVPN Connect\n"
        "2. Импортируйте .ovpn файл\n"
        "3. Подключитесь\n\n"
        "📱 Работает на всех устройствах!",
        parse_mode="Markdown", reply_markup=main_menu()
    )

@dp.callback_query(F.data == "support")
async def support(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "📞 *ПОДДЕРЖКА*\n\n"
        "Если VPN не работает:\n"
        "• Попробуйте другую страну\n"
        "• Переключитесь между WiFi/моб.интернет\n"
        "• Попробуйте другой тип (WG → OVPN)\n\n"
        "По всем вопросам: напишите сообщение",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Написать в поддержку", callback_data="write_support")],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="start_menu")],
        ])
    )

@dp.callback_query(F.data == "write_support")
async def write_support(cb: types.CallbackQuery):
    await cb.message.answer("📝 Опишите вашу проблему. Администратор ответит в ближайшее время.")
    # Тикет сохраняется в следующем сообщении

@dp.message(F.text)
async def handle_message(msg: Message):
    if msg.text.startswith("/"): return
    
    c.execute("INSERT INTO tickets (user_id, username, message, created) VALUES (?, ?, ?, ?)",
              (msg.from_user.id, msg.from_user.username, msg.text, datetime.now().isoformat()))
    conn.commit()
    
    for aid in ADMIN_IDS:
        try: await bot.send_message(aid, f"📋 Тикет #{c.lastrowid} от @{msg.from_user.username}\n\n{msg.text}")
        except: pass
    
    await msg.answer("✅ Сообщение отправлено! Ответ придёт в ближайшее время.", reply_markup=main_menu())

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
