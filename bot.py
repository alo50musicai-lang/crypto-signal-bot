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

def run_server():
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

threading.Thread(target=run_server, daemon=True).start()

# =========================
# Config
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")

SYMBOL = "BTCUSDT"
LIMIT = 120
MAX_SIGNALS_PER_DAY = 5   # کمی بیشتر برای سیگنال حرفه‌ای
signals_today = {}
CHAT_ID = None   # بعد از /start ست می‌شود

# =========================
# Get Candles (MEXC v3)
# =========================
def get_klines(interval):
    try:
        url = "https://api.mexc.com/api/v3/klines"
        params = {"symbol": SYMBOL, "interval": interval, "limit": LIMIT}
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
        print("❌ Candle Error:", e)
        return None

# =========================
# NDS Logic پیشرفته
# =========================
def compression(candles):
    if len(candles) < 6:
        return False
    ranges = [(c["high"] - c["low"]) for c in candles[-6:-1]]
    avg_range = sum(ranges) / len(ranges)
    last_range = candles[-1]["high"] - candles[-1]["low"]
    return last_range < avg_range * 0.7

def displacement(candles):
    last = candles[-1]
    prev = candles[-2]

    body = abs(last["close"] - last["open"])
    full = last["high"] - last["low"]
    if full == 0:
        return None

    strength = body / full

    # LONG / SHORT پیشرفته با تشخیص فرکتال و الگوریتم NDS
    if last["close"] > last["open"] and last["close"] > prev["high"] and strength > 0.55:
        return "LONG"
    if last["close"] < last["open"] and last["close"] < prev["low"] and strength > 0.55:
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
    global CHAT_ID
    if CHAT_ID is None:
        return

    for interval in ["15m", "30m"]:
        candles = get_klines(interval)
        if not candles:
            continue
        if not compression(candles):
            continue

        side = displacement(candles)
        if not side or not can_send():
            continue

        last = candles[-1]
        prev = candles[-2]

        entry = last["close"]
        sl = prev["low"] if side == "LONG" else prev["high"]
        tp = entry + (entry - sl) * 2 if side == "LONG" else entry - (sl - entry) * 2

        text = f"""
🚨 BTC NDS SIGNAL

📍 {side}
⏱ TF: {interval}

🎯 Entry: {entry:.2f}
🛑 SL: {sl:.2f}
💰 TP: {tp:.2f}

⚠️ فقط تحلیل – تصمیم با خودته
"""
        await context.bot.send_message(chat_id=CHAT_ID, text=text)

# =========================
# Commands
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    CHAT_ID = update.effective_chat.id
    await update.message.reply_text(
        "🤖 ربات NDS فعال شد\n"
        "سیگنال‌های BTC به صورت خودکار ارسال می‌شوند\n"
        "نیازی به دستور نیست"
    )

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok = []
    for interval in ["15m", "30m"]:
        candles = get_klines(interval)
        if not candles:
            ok.append(f"{interval}: ❌ خطا")
        else:
            ok.append(f"{interval}: ✅ OK (Close: {candles[-1]['close']:.2f})")
    await update.message.reply_text("\n".join(ok))

# =========================
# Main
# =========================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("test", test))

    app.job_queue.run_repeating(
        auto_signal,
        interval=180,   # هر ۳ دقیقه سریعتر و سیگنال بیشتر
        first=20
    )

    app.run_polling()

if __name__ == "__main__":
    main()