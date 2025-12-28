import os
import threading
import requests
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================
# Fake Web Server (برای Render)
# =========================
PORT = int(os.getenv("PORT", 10000))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

threading.Thread(target=run_server:=lambda: HTTPServer(("0.0.0.0", PORT), Handler).serve_forever(), daemon=True).start()

# =========================
# Config
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")
SYMBOL = "BTC_USDT"
INTERVAL = "15m"
LIMIT = 120
MAX_SIGNALS_PER_DAY = 3

signals_today = {}

# =========================
# Get Candles (MEXC)
# =========================
def get_klines():
    try:
        url = "https://www.mexc.com/open/api/v2/market/kline"
        params = {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "limit": LIMIT
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        candles = []
        klines = data["data"]
        for i in range(len(klines["time"])):
            candles.append({
                "open": float(klines["open"][i]),
                "high": float(klines["high"][i]),
                "low": float(klines["low"][i]),
                "close": float(klines["close"][i]),
            })
        return candles
    except Exception as e:
        print("❌ Candle Error:", e)
        return None

# =========================
# NDS + Break + Retest
# =========================
def compression(candles):
    ranges = [(c["high"] - c["low"]) for c in candles[-6:-1]]
    avg_range = sum(ranges) / len(ranges)
    last_range = candles[-1]["high"] - candles[-1]["low"]
    return last_range < avg_range * 0.8  # کمی کمتر حساسیت

def displacement(candles):
    last = candles[-1]
    prev = candles[-2]

    body = abs(last["close"] - last["open"])
    full = last["high"] - last["low"]
    if full == 0:
        return None

    strength = body / full

    # LONG: شکست مقاومت + retest
    if last["close"] > prev["high"] and strength > 0.5:
        return "LONG"
    # SHORT: شکست حمایت + retest
    if last["close"] < prev["low"] and strength > 0.5:
        return "SHORT"

    return None

# =========================
# Signal Limit
# =========================
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
    candles = get_klines()
    if not candles:
        return
    if not compression(candles):
        return

    side = displacement(candles)
    if not side or not can_send():
        return

    last = candles[-1]
    prev = candles[-2]
    entry = last["close"]
    sl = prev["low"] if side == "LONG" else prev["high"]
    tp = entry + (entry - sl) * 2 if side == "LONG" else entry - (sl - entry) * 2

    text = f"""
🚨 BTC NDS + Break Signal

📍 {side}
⏱ TF: 15m

🎯 Entry: {entry:.2f}
🛑 SL: {sl:.2f}
💰 TP: {tp:.2f}

⚠️ فقط تحلیل – تصمیم با خودته
"""

    # ارسال به چت ربات خود
    await context.bot.send_message(chat_id=context.bot.id, text=text)

# =========================
# Commands
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 ربات NDS فعال شد\n"
        "سیگنال‌های BTC به صورت خودکار ارسال می‌شوند\n"
        "نیازی به دستور نیست"
    )

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    candles = get_klines()
    if not candles:
        await update.message.reply_text("❌ خطا در دریافت دیتا")
        return
    last = candles[-1]
    await update.message.reply_text(f"✅ اتصال OK\nBTC Close: {last['close']}")

# =========================
# Main
# =========================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))
    app.job_queue.run_repeating(auto_signal, interval=300, first=15)
    app.run_polling()

if __name__ == "__main__":
    main()