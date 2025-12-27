import os
import threading
import requests
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", 10000))

# ======================
# Fake Web Server
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
# Binance Candles
# ======================
def get_klines(symbol="BTCUSDT", interval="5m", limit=100):
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
        data = r.json()
    except:
        return None

    if not isinstance(data, list):
        return None

    candles = []
    for k in data:
        try:
            candles.append({
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
            })
        except:
            return None

    if len(candles) < 3:
        return None
    return candles

# ======================
# Market Structure
# ======================
def market_structure(candles):
    if candles[-1]["high"] > candles[-2]["high"] and candles[-1]["low"] > candles[-2]["low"]:
        return "BULLISH"
    if candles[-1]["high"] < candles[-2]["high"] and candles[-1]["low"] < candles[-2]["low"]:
        return "BEARISH"
    return "RANGE"

# ======================
# Price Action
# ======================
def price_action(candle, direction):
    body = abs(candle["close"] - candle["open"])
    range_ = candle["high"] - candle["low"]
    if range_ <= 0:
        return False
    strength = body / range_
    if direction == "LONG" and candle["close"] > candle["open"] and strength > 0.6:
        return True
    if direction == "SHORT" and candle["close"] < candle["open"] and strength > 0.6:
        return True
    return False

# ======================
# Build Signal
# ======================
def build_signal(symbol, interval):
    candles = get_klines(symbol, interval)
    if not candles:
        return None
    structure = market_structure(candles)
    last, prev = candles[-1], candles[-2]

    if structure == "BULLISH" and price_action(last, "LONG"):
        entry = last["close"]
        sl = prev["low"]
        tp = entry + (entry - sl) * 2
        return "LONG", entry, sl, tp

    if structure == "BEARISH" and price_action(last, "SHORT"):
        entry = last["close"]
        sl = prev["high"]
        tp = entry - (sl - entry) * 2
        return "SHORT", entry, sl, tp

    return None

# ======================
# Limit 3 signals/day
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
    symbols = ["BTCUSDT", "ETHUSDT"]
    timeframes = ["5m", "15m", "30m"]

    for symbol in symbols:
        if not can_send(symbol):
            await update.message.reply_text(f"⛔️ سقف سیگنال امروز {symbol} پر شده")
            continue

        msg = f"📊 {symbol}\n"

        for tf in timeframes:
            signal = build_signal(symbol, tf)
            if signal:
                side, entry, sl, tp = signal
                msg += f"\n🕒 TF: {tf}\n{'🟢 LONG' if side=='LONG' else '🔴 SHORT'}\n🎯 Entry: {entry:.2f}\n🛑 SL: {sl:.2f}\n💰 TP: {tp:.2f}\n"
            else:
                msg += f"\n🕒 TF: {tf}\n⏸ شرایط ورود مناسب نیست\n"

        msg += "\n⚠️ ریسک متوسط – فقط تحلیل"
        await update.message.reply_text(msg)

# ======================
# Main
# ======================
def main():
    threading.Thread(target=run_server).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()