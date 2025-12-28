import os
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
# GET CANDLES
# =====================
def get_klines():
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": SYMBOL, "interval": INTERVAL, "limit": LIMIT}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        candles = []
        for k in data:
            candles.append({
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
            })
        return candles
    except Exception as e:
        print("❌ Candle error:", e)
        return None

# =====================
# NDS LOGIC
# =====================
def compression(candles):
    ranges = [(c["high"] - c["low"]) for c in candles[-6:-1]]
    avg = sum(ranges) / len(ranges)
    last_range = candles[-1]["high"] - candles[-1]["low"]
    return last_range < avg * 0.7

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
    signals_today.setdefault(today, 0)
    if signals_today[today] >= MAX_SIGNALS_PER_DAY:
        return False
    signals_today[today] += 1
    return True

# =====================
# AUTO SIGNAL (JOB)
# =====================
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
🚨 NDS SIGNAL – BTC

📍 {side}
⏱ TF: {INTERVAL}

🎯 Entry: {entry:.2f}
🛑 SL: {sl:.2f}
💰 TP: {tp:.2f}

⚠️ فقط تحلیل – تصمیم با خودته
"""
    await context.bot.send_message(chat_id=context.bot.id, text=text)

# =====================
# COMMANDS
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 ربات NDS فعال شد\n"
        "سیگنال‌های BTC به‌صورت خودکار ارسال می‌شوند\n"
        "نیازی به دستور خاصی نیست"
    )

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    candles = get_klines()
    if not candles:
        await update.message.reply_text("❌ خطا در دریافت دیتا")
        return
    last = candles[-1]
    await update.message.reply_text(
        f"✅ اتصال OK\nBTC Close: {last['close']}"
    )

# =====================
# MAIN
# =====================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))

    app.job_queue.run_repeating(auto_signal, interval=300, first=15)

    app.run_polling()

if __name__ == "__main__":
    main()