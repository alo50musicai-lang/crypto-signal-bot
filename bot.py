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
# DATA (کندل ها)
# ======================
def get_klines(symbol="BTCUSDT", interval="5m", limit=200):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
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
# Price Action
# ======================
def detect_structure(candles):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "BULLISH"
    elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "BEARISH"
    else:
        return "RANGE"


# ======================
# Risk (حداکثر ۳ سیگنال در روز)
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
    # BTC
    symbol = "BTCUSDT"
    timeframe = "5m"
    candles = get_klines(symbol, timeframe)
    structure = detect_structure(candles)

    if not can_send(symbol):
        await update.message.reply_text("⛔️ سقف سیگنال امروز BTC پر شده")
    else:
        await update.message.reply_text(
            f"""
📊 {symbol}
🕒 TF: {timeframe}
📈 Market Structure: {structure}

⚠️ فقط تحلیل – تصمیم با خودته
"""
        )

    # ETH
    symbol2 = "ETHUSDT"
    candles2 = get_klines(symbol2, timeframe)
    structure2 = detect_structure(candles2)

    if not can_send(symbol2):
        await update.message.reply_text("⛔️ سقف سیگنال امروز ETH پر شده")
    else:
        await update.message.reply_text(
            f"""
📊 {symbol2}
🕒 TF: {timeframe}
📈 Market Structure: {structure2}

⚠️ فقط تحلیل – تصمیم با خودته
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