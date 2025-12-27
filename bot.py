import os
import threading
import requests
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ======================
# تنظیمات
# ======================
TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", 10000))

# ======================
# Fake Web Server برای Render
# ======================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), SimpleHandler)
    server.serve_forever()

# ======================
# DATA from MEXC (بدون تحریم)
# ======================
def get_klines(symbol="BTCUSDT", interval="5m", limit=200):
    url = "https://api.mexc.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    r = requests.get(url, params=params, timeout=10)
    data = r.json()

    candles = []
    for k in data:
        candles.append({
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5])
        })

    return candles

# ======================
# Price Action (Market Structure)
# ======================
def detect_structure(candles):
    if len(candles) < 2:
        return "NOT ENOUGH DATA"

    last = candles[-1]
    prev = candles[-2]

    if last["high"] > prev["high"] and last["low"] > prev["low"]:
        return "BULLISH STRUCTURE"
    elif last["high"] < prev["high"] and last["low"] < prev["low"]:
        return "BEARISH STRUCTURE"
    else:
        return "RANGE / CONSOLIDATION"

# ======================
# Risk Management (۳ سیگنال در روز)
# ======================
signals_today = {}

def can_send(symbol):
    today = date.today().isoformat()
    key = f"{symbol}_{today}"

    if key not in signals_today:
        signals_today[key] = 0

    if signals_today[key] >= 3:
        return False

    signals_today[key] += 1
    return True

# ======================
# Telegram Command
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    timeframe = "5m"

    for symbol in ["BTCUSDT", "ETHUSDT"]:
        candles = get_klines(symbol, timeframe)
        structure = detect_structure(candles)

        if not can_send(symbol):
            await update.message.reply_text(f"⛔️ سقف سیگنال امروز {symbol} پر شده")
        else:
            await update.message.reply_text(
                f"""
📊 {symbol}
🕒 TF: {timeframe}
📈 Market Structure: {structure}

⚠️ فقط تحلیل است
تصمیم ورود یا خروج با خودت
"""
            )

# ======================
# Main
# ======================
def run_bot():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_server).start()
    run_bot()