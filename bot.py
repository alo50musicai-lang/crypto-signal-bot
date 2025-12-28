import os
import asyncio
import requests
from datetime import date
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =====================
# CONFIG
# =====================
TOKEN = os.getenv("TELEGRAM_TOKEN")
SYMBOL = "BTCUSDT"
INTERVAL = "15m"
LIMIT = 120
MAX_SIGNALS_PER_DAY = 3

signals_today = {}

# =====================
# GET CANDLES (BINANCE)
# =====================
def get_klines():
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "limit": LIMIT
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        candles = []
        for k in data:
            candles.append({
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4])
            })
        return candles

    except Exception as e:
        print("❌ Candle error:", e)
        return None

# =====================
# NDS LOGIC
# =====================
def is_compression(candles):
    last = candles[-1]
    ranges = [(c["high"] - c["low"]) for c in candles[-6:-1]]
    avg_range = sum(ranges) / len(ranges)
    return (last["high"] - last["low"]) < avg_range * 0.75

def displacement(candles):
    last = candles[-1]
    prev = candles[-2]

    body = abs(last["close"] - last["open"])
    full = last["high"] - last["low"]
    if full == 0:
        return None

    strength = body / full

    if last["close"] > last["open"] and last["close"] > prev["high"] and strength > 0.55:
        return "LONG"

    if last["close"] < last["open"] and last["close"] < prev["low"] and strength > 0.55:
        return "SHORT"

    return None

# =====================
# SIGNAL LIMIT
# =====================
def can_send():
    today = date.today().isoformat()
    if today not in signals_today:
        signals_today[today] = 0

    if signals_today[today] >= MAX_SIGNALS_PER_DAY:
        return False

    signals_today[today] += 1
    return True

# =====================
# AUTO SIGNAL LOOP
# =====================
async def auto_signal(app: Application):
    await asyncio.sleep(10)

    while True:
        candles = get_klines()
        if candles and is_compression(candles):
            side = displacement(candles)

            if side and can_send():
                last = candles[-1]
                prev = candles[-2]

                entry = last["close"]
                sl = prev["low"] if side == "LONG" else prev["high"]
                tp = entry + (entry - sl) * 2 if side == "LONG" else entry - (sl - entry) * 2

                text = f"""
🚨 NDS SIGNAL – BTC

📍 {side}
⏱ TF: {INTERVAL}

🎯 Entry: {entry:.2f}
🛑 SL: {sl:.2f}
💰 TP: {tp:.2f}

⚠️ فقط تحلیل – مسئولیت با خودت
"""
                await app.bot.send_message(chat_id=app.bot.id, text=text)

        await asyncio.sleep(300)  # هر 5 دقیقه

# =====================
# TEST COMMAND
# =====================
async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    candles = get_klines()
    if not candles:
        await update.message.reply_text("❌ خطا در دریافت دیتا")
        return

    last = candles[-1]
    await update.message.reply_text(
        f"""
✅ اتصال برقرار است

BTCUSDT {INTERVAL}

Open: {last['open']}
High: {last['high']}
Low: {last['low']}
Close: {last['close']}
"""
    )

# =====================
# START
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 ربات NDS فعال شد!\n"
        "سیگنال‌های BTC به صورت خودکار ارسال می‌شوند.\n\n"
        "برای تست دستور /test را بزن."
    )

# =====================
# MAIN
# =====================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))

    app.create_task(auto_signal(app))
    app.run_polling()

if __name__ == "__main__":
    main()