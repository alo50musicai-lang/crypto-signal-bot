import os
import threading
import requests
import numpy as np
import pandas as pd
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", 10000))
CRYPTOPANIC_API = os.getenv("CRYPTOPANIC_API")  # اختیاری برای اخبار

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
# Binance Candles
# ======================
def get_klines(symbol="BTCUSDT", interval="5m", limit=200):
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
                "volume": float(k[5])
            })
        except:
            return None

    if len(candles) < 3:
        return None
    return candles

# ======================
# تبدیل به DataFrame برای اندیکاتورها
# ======================
def to_dataframe(candles):
    df = pd.DataFrame(candles)
    df['EMA9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    df['MACD'] = df['close'].ewm(span=12, adjust=False).mean() - df['close'].ewm(span=26, adjust=False).mean()
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    return df

# ======================
# کندل شناسی ساده
# ======================
def candlestick_pattern(candle, prev):
    # Bullish Engulfing
    if candle['close'] > candle['open'] and prev['close'] < prev['open'] and candle['close'] > prev['open'] and candle['open'] < prev['close']:
        return "BULLISH_ENGULFING"
    # Bearish Engulfing
    if candle['close'] < candle['open'] and prev['close'] > prev['open'] and candle['close'] < prev['open'] and candle['open'] > prev['close']:
        return "BEARISH_ENGULFING"
    # Hammer
    body = abs(candle['close'] - candle['open'])
    lower = candle['open'] - candle['low'] if candle['close'] > candle['open'] else candle['close'] - candle['low']
    upper = candle['high'] - candle['close'] if candle['close'] > candle['open'] else candle['high'] - candle['open']
    if lower > 2 * body and upper < body:
        return "HAMMER"
    # Shooting Star
    if upper > 2 * body and lower < body:
        return "SHOOTING_STAR"
    return None

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
# NDS ساده
# ======================
def nds_trend(candles):
    highs = [c["high"] for c in candles[-5:]]
    lows = [c["low"] for c in candles[-5:]]
    if sum([highs[i]-highs[i-1] for i in range(1,5)]) > 0 and sum([lows[i]-lows[i-1] for i in range(1,5)]) > 0:
        return "BULLISH"
    if sum([highs[i]-highs[i-1] for i in range(1,5)]) < 0 and sum([lows[i]-lows[i-1] for i in range(1,5)]) < 0:
        return "BEARISH"
    return "RANGE"

# ======================
# Elliott Wave ساده
# ======================
def elliott_wave(candles):
    if candles[-1]["close"] > candles[-2]["close"] and candles[-2]["close"] > candles[-3]["close"]:
        return "BULLISH"
    if candles[-1]["close"] < candles[-2]["close"] and candles[-2]["close"] < candles[-3]["close"]:
        return "BEARISH"
    return "NEUTRAL"

# ======================
# اخبار کریپتو
# ======================
def check_news(symbol):
    if not CRYPTOPANIC_API:
        return False
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_API}&currencies={symbol[:3]}"
        r = requests.get(url, timeout=5).json()
        for post in r.get("results", []):
            if post["importance"] == "high":
                return True
    except:
        return False
    return False

# ======================
# Build Signal
# ======================
def build_signal(symbol, interval):
    candles = get_klines(symbol, interval)
    if not candles:
        return None
    df = to_dataframe(candles)
    ms = "BULLISH" if df['close'].iloc[-1] > df['close'].iloc[-2] else "BEARISH"
    nds = nds_trend(candles)
    wave = elliott_wave(candles)
    news = check_news(symbol)
    pattern = candlestick_pattern(candles[-1], candles[-2])

    # شرط نهایی: همه فاکتورها هم‌جهت
    if ms == "BULLISH" and nds == "BULLISH" and wave == "BULLISH" and not news and price_action(candles[-1], "LONG"):
        entry = candles[-1]["close"]
        sl = candles[-2]["low"]
        tp = entry + (entry - sl) * 2
        return "LONG", entry, sl, tp, pattern

    if ms == "BEARISH" and nds == "BEARISH" and wave == "BEARISH" and not news and price_action(candles[-1], "SHORT"):
        entry = candles[-1]["close"]
        sl = candles[-2]["high"]
        tp = entry - (sl - entry) * 2
        return "SHORT", entry, sl, tp, pattern

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
# Telegram Command
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTCUSDT"
    timeframes = ["5m", "15m", "30m"]

    if not can_send(symbol):
        await update.message.reply_text(f"⛔️ سقف سیگنال امروز {symbol} پر شده")
        return

    msg = f"📊 {symbol}\n"
    for tf in timeframes:
        signal = build_signal(symbol, tf)
        if signal:
            side, entry, sl, tp, pattern = signal
            msg += f"\n🕒 TF: {tf}\n{'🟢 LONG' if side=='LONG' else '🔴 SHORT'}\n🎯 Entry: {entry:.2f}\n🛑 SL: {sl:.2f}\n💰 TP: {tp:.2f}\n📌 Pattern: {pattern}\n"
        else:
            msg += f"\n🕒 TF: {tf}\n⏸ شرایط ورود مناسب نیست یا خبر منفی\n"

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