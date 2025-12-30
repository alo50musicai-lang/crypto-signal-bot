import os
import json
import threading
import requests
from datetime import date, datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================
# Fake Web Server (Render)
# =========================
PORT = int(os.getenv("PORT", 10000))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_server():
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# =========================
# Config
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")
SYMBOL = "BTCUSDT"
LIMIT = 120

MAX_SIGNALS_PER_DAY = 3

signals_today = {}

# =========================
# VIP STORAGE
# =========================
VIP_FILE = "vip_users.json"
VIP_USERS = set()
ADMIN_ID = None

def load_vips():
    global VIP_USERS, ADMIN_ID
    if os.path.exists(VIP_FILE):
        with open(VIP_FILE, "r") as f:
            data = json.load(f)
            VIP_USERS = set(data.get("vips", []))
            ADMIN_ID = data.get("admin")

def save_vips():
    with open(VIP_FILE, "w") as f:
        json.dump({"admin": ADMIN_ID, "vips": list(VIP_USERS)}, f)

load_vips()

# =========================
# Market Data
# =========================
def get_klines(interval):
    try:
        r = requests.get(
            "https://api.mexc.com/api/v3/klines",
            params={"symbol": SYMBOL, "interval": interval, "limit": LIMIT},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        return [{
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4])
        } for k in data]
    except:
        return None

def get_price():
    try:
        r = requests.get(
            "https://api.mexc.com/api/v3/ticker/price",
            params={"symbol": SYMBOL},
            timeout=5
        )
        return float(r.json()["price"])
    except:
        return None

# =========================
# Logic
# =========================
def market_bias(candles):
    if candles[-1]["close"] > candles[-4]["close"]:
        return "LONG"
    if candles[-1]["close"] < candles[-4]["close"]:
        return "SHORT"
    return None

def can_send():
    today = date.today().isoformat()
    signals_today.setdefault(today, 0)
    if signals_today[today] >= MAX_SIGNALS_PER_DAY:
        return False
    signals_today[today] += 1
    return True

# =========================
# Auto Signal
# =========================
async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    for chat_id in VIP_USERS:
        for tf in ["15m", "30m", "1h"]:
            candles = get_klines(tf)
            if not candles:
                continue

            bias = market_bias(candles)
            if not bias:
                continue

            iran_time = datetime.utcnow() + timedelta(hours=3, minutes=30)
            time_str = iran_time.strftime("%Y-%m-%d | %H:%M")

            last = candles[-1]
            prev = candles[-2]

            # Entry zone ساده و امن
            entry_zone = (
                (last["close"] + prev["low"]) / 2
                if bias == "LONG"
                else (last["close"] + prev["high"]) / 2
            )

            invalidation = prev["low"] if bias == "LONG" else prev["high"]

            if not can_send():
                continue

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"""
📊 BTC MARKET BIAS ALERT

Bias: {bias}
TF: {tf}
🕒 Time (IR): {time_str}

💡 سناریوی محتمل:
اگر قیمت به ناحیه مشخص‌شده واکنش بده،
می‌تواند فرصت {bias} باشد.

📍 Entry Zone: {entry_zone:.2f}
❌ Invalidation: {invalidation:.2f}

⚠️ ربات فقط سناریو می‌دهد
🧠 تصمیم نهایی با شما
"""
            )

# =========================
# Commands
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_ID
    cid = update.effective_chat.id

    if ADMIN_ID is None:
        ADMIN_ID = cid
        VIP_USERS.add(cid)
        save_vips()
        await update.message.reply_text("👑 شما ادمین شدید")
    elif cid in VIP_USERS:
        await update.message.reply_text("✅ دسترسی VIP فعال است")
    else:
        await update.message.reply_text("⏳ در انتظار تأیید ادمین")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = get_price()
    msgs = []

    for tf in ["15m", "30m", "1h"]:
        candles = get_klines(tf)
        if candles:
            bias = market_bias(candles)
            msgs.append(f"{tf}: {bias}")

    await update.message.reply_text(
        f"""
🧪 BTC MARKET TEST

💰 Price: {price:.2f} USDT
📊 Bias:
""" + "\n".join(msgs)
    )

# =========================
# Main
# =========================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))

    app.job_queue.run_repeating(auto_signal, interval=180, first=20)
    app.run_polling()

if __name__ == "__main__":
    main()