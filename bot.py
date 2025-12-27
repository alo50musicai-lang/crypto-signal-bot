import os
import requests
from datetime import date
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")

# ======================
# دریافت کندل‌ها (ایمن)
# ======================
def get_klines(symbol="BTCUSDT", interval="5m", limit=100):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    try:
        r = requests.get(url, params=params, timeout=10)
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
# ساخت سیگنال
# ======================
def build_signal(symbol):
    candles = get_klines(symbol)
    if not candles:
        return None

    structure = market_structure(candles)
    last = candles[-1]
    prev = candles[-2]

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
# محدودیت روزانه
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
        if not can_send(symbol):
            await update.message.reply_text(f"⛔️ سقف سیگنال امروز {symbol} پر شده")
            continue

        signal = build_signal(symbol)

        if not signal:
            await update.message.reply_text(
                f"⏸ {symbol}\nفعلاً شرایط ورود مناسب نیست"
            )
            continue

        side, entry, sl, tp = signal

        await update.message.reply_text(
            f"""
📊 {symbol}
🕒 TF: {timeframe}

{'🟢 LONG' if side == 'LONG' else '🔴 SHORT'}

🎯 Entry: {entry:.2f}
🛑 Stop Loss: {sl:.2f}
💰 Take Profit: {tp:.2f}

⚠️ ریسک متوسط – فقط تحلیل
"""
        )

# ======================
# Main
# ======================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()