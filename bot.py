import os
import threading
import requests
import random
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import pandas as pd

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
# دریافت کندل‌ها
# ======================
def get_klines(symbol="BTCUSDT", interval="5m", limit=100):
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
    if range_ == 0:
        return False
    strength = body / range_
    if direction == "LONG" and candle["close"] > candle["open"] and strength > 0.6:
        return True
    if direction == "SHORT" and candle["close"] < candle["open"] and strength > 0.6:
        return True
    return False

# ======================
# EMA / RSI / Volume
# ======================
def indicators_confirm(candles, direction):
    df = pd.DataFrame(candles)
    df["EMA9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["EMA21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["diff"] = df["EMA9"] - df["EMA21"]
    df["RSI"] = 100 - (100 / (1 + (df["close"].diff().clip(lower=0).rolling(14).mean() /
                                   df["close"].diff().abs().rolling(14).mean())))
    df["volume_avg"] = df["volume"].rolling(20).mean()
    last = df.iloc[-1]

    if direction == "LONG":
        return last["diff"] > 0 and last["RSI"] > 50 and last["volume"] > last["volume_avg"]
    if direction == "SHORT":
        return last["diff"] < 0 and last["RSI"] < 50 and last["volume"] > last["volume_avg"]
    return False

# ======================
# حمایت/مقاومت و NDS
# ======================
def get_support_resistance(candles, n=50):
    highs = [c["high"] for c in candles[-n:]]
    lows = [c["low"] for c in candles[-n:]]
    resistance = max(highs)
    support = min(lows)
    return support, resistance

def nds_filter(candles, direction):
    support, resistance = get_support_resistance(candles)
    last_close = candles[-1]["close"]
    if direction == "LONG" and last_close < resistance:
        return True
    if direction == "SHORT" and last_close > support:
        return True
    return False

# ======================
# بررسی اخبار ساده (10% احتمال خبر مهم)
# ======================
def check_news():
    return random.randint(1, 10) == 1

# ======================
# بررسی شکست ترند یا حمایت/مقاومت
# ======================
def trend_break(candles, direction):
    support, resistance = get_support_resistance(candles)
    last_close = candles[-1]["close"]
    if direction == "LONG" and last_close > resistance:
        return True
    if direction == "SHORT" and last_close < support:
        return True
    return False

# ======================
# ساخت سیگنال
# ======================
def build_signal(symbol, interval):
    if check_news():
        return "NEWS_BLOCK", None, None, None, None

    candles = get_klines(symbol, interval)
    structure = market_structure(candles)
    last = candles[-1]
    prev = candles[-2]

    if structure == "BULLISH" and price_action(last, "LONG") and indicators_confirm(candles, "LONG") and nds_filter(candles, "LONG"):
        entry = last["close"]
        sl = prev["low"]
        tp = entry + (entry - sl) * 2
        reason = "BULLISH + PriceAction + EMA/RSI + NDS + Support OK"
        return "LONG", entry, sl, tp, reason

    if structure == "BEARISH" and price_action(last, "SHORT") and indicators_confirm(candles, "SHORT") and nds_filter(candles, "SHORT"):
        entry = last["close"]
        sl = prev["high"]
        tp = entry - (sl - entry) * 2
        reason = "BEARISH + PriceAction + EMA/RSI + NDS + Resistance OK"
        return "SHORT", entry, sl, tp, reason

    # بررسی شکست ترند
    if trend_break(candles, "LONG"):
        return "TREND_BREAK_LONG", last["close"], prev["low"], last["close"] + (last["close"] - prev["low"]) * 2, "Break Resistance"
    if trend_break(candles, "SHORT"):
        return "TREND_BREAK_SHORT", last["close"], prev["high"], prev["high"] - (last["close"] - prev["high"]) * 2, "Break Support"

    return None

# ======================
# محدودیت ۳ سیگنال در روز
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
# دستور /start تلگرام
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTCUSDT"
    for interval in ["5m", "15m", "30m"]:
        if not can_send(symbol):
            await update.message.reply_text(f"⛔️ سقف سیگنال امروز {symbol} پر شده")
            continue

        signal = build_signal(symbol, interval)

        if signal is None:
            await update.message.reply_text(f"⏸ {symbol} ({interval})\nفعلاً شرایط ورود مناسب نیست")
            continue

        if signal[0] == "NEWS_BLOCK":
            await update.message.reply_text(f"⚠️ خبر مهم منتشر شده، ورود در حال حاضر توصیه نمی‌شود ({interval})")
            continue

        side, entry, sl, tp, reason = signal
        await update.message.reply_text(
            f"""
📊 {symbol}
🕒 TF: {interval}

{'🟢 LONG' if side=='LONG' else '🔴 SHORT'}

🎯 Entry: {entry:.2f}
🛑 Stop Loss: {sl:.2f}
💰 Take Profit: {tp:.2f}

✅ دلیل: {reason}

⚠️ ریسک متوسط – فقط تحلیل
"""
        )

# ======================
# Main
# ======================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    threading.Thread(target=run_server).start()
    app.run_polling()

if __name__ == "__main__":
    main()