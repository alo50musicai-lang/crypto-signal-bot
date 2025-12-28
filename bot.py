import os
import threading
import requests
import random
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import pandas as pd

# ======================
# تنظیمات
# ======================
TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", 10000))
SYMBOL = "BTCUSDT"
TIMEFRAMES = ["5m", "15m", "30m"]

# ======================
# Fake Web Server (Render)
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
# دریافت کندل‌ها (Safe)
# ======================
def get_klines(interval, limit=120):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": SYMBOL, "interval": interval, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        candles = []
        for k in data:
            try:
                candles.append({
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5])
                })
            except:
                continue
        return candles
    except:
        return []

# ======================
# تحلیل‌ها
# ======================
def market_structure(c):
    if c[-1]["high"] > c[-2]["high"] and c[-1]["low"] > c[-2]["low"]:
        return "BULLISH"
    if c[-1]["high"] < c[-2]["high"] and c[-1]["low"] < c[-2]["low"]:
        return "BEARISH"
    return "RANGE"

def price_action(candle, side):
    body = abs(candle["close"] - candle["open"])
    rng = candle["high"] - candle["low"]
    if rng == 0:
        return False
    power = body / rng
    if side == "LONG":
        return candle["close"] > candle["open"] and power > 0.6
    if side == "SHORT":
        return candle["close"] < candle["open"] and power > 0.6
    return False

def indicators(candles, side):
    df = pd.DataFrame(candles)
    df["ema9"] = df["close"].ewm(span=9).mean()
    df["ema21"] = df["close"].ewm(span=21).mean()
    df["rsi"] = 100 - (100 / (1 + (df["close"].diff().clip(lower=0).rolling(14).mean() /
                                   df["close"].diff().abs().rolling(14).mean())))
    last = df.iloc[-1]
    if side == "LONG":
        return last["ema9"] > last["ema21"] and last["rsi"] > 50
    if side == "SHORT":
        return last["ema9"] < last["ema21"] and last["rsi"] < 50
    return False

def support_resistance(c):
    highs = [x["high"] for x in c[-50:]]
    lows = [x["low"] for x in c[-50:]]
    return min(lows), max(highs)

# ======================
# محدودیت ۳ سیگنال
# ======================
signals_today = {}

def can_send():
    today = date.today().isoformat()
    if today not in signals_today:
        signals_today[today] = 0
    if signals_today[today] >= 3:
        return False
    signals_today[today] += 1
    return True

# ======================
# ساخت سیگنال
# ======================
def analyze(interval):
    candles = get_klines(interval)
    if len(candles) < 50:
        return "⛔️ دیتا کافی نیست"

    structure = market_structure(candles)
    last = candles[-1]
    prev = candles[-2]
    sup, res = support_resistance(candles)

    if structure == "BULLISH" and price_action(last, "LONG") and indicators(candles, "LONG"):
        entry = last["close"]
        sl = prev["low"]
        tp = entry + (entry - sl) * 2
        return f"""🟢 LONG BTC
TF: {interval}

Entry: {entry:.2f}
SL: {sl:.2f}
TP: {tp:.2f}

Structure: Bullish
"""

    if structure == "BEARISH" and price_action(last, "SHORT") and indicators(candles, "SHORT"):
        entry = last["close"]
        sl = prev["high"]
        tp = entry - (sl - entry) * 2
        return f"""🔴 SHORT BTC
TF: {interval}

Entry: {entry:.2f}
SL: {sl:.2f}
TP: {tp:.2f}

Structure: Bearish
"""

    return f"⏸ BTC ({interval})\nشرایط ورود مناسب نیست"

# ======================
# منو
# ======================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 بررسی بازار BTC", callback_data="scan")],
        [InlineKeyboardButton("📊 تحلیل 5m / 15m / 30m", callback_data="analysis")],
        [InlineKeyboardButton("ℹ️ وضعیت امروز", callback_data="status")]
    ])

# ======================
# Handlers
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 ربات تحلیل BTC فعال است\nانتخاب کن:",
        reply_markup=main_menu()
    )

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "status":
        today = date.today().isoformat()
        used = signals_today.get(today, 0)
        await q.message.reply_text(f"📊 سیگنال‌های امروز: {used}/3")

    if q.data in ["scan", "analysis"]:
        if not can_send():
            await q.message.reply_text("⛔️ سقف ۳ سیگنال امروز پر شده")
            return
        for tf in TIMEFRAMES:
            await q.message.reply_text(analyze(tf))

# ======================
# Main
# ======================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_handler))
    threading.Thread(target=run_server).start()
    app.run_polling()

if __name__ == "__main__":
    main()