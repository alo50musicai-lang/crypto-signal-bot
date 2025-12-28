import os
import requests
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# ======================
# تنظیمات
# ======================
TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", 10000))

SYMBOL = "BTCUSDT"
TF = "15m"

# ======================
# Web Server (برای Render)
# ======================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_server():
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

# ======================
# دریافت کندل‌ها با مدیریت خطا
# ======================
def get_klines(limit=120):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": SYMBOL, "interval": TF, "limit": limit}
    
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print("❌ خطا در دریافت دیتای کندل:", e)
        return []

    candles = []
    for k in data:
        try:
            candles.append({
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4])
            })
        except Exception as e:
            print("❌ خطا در تبدیل داده کندل:", k, e)
            continue

    return candles

# ======================
# NDS – Compression
# ======================
def is_compression(candles):
    if len(candles) < 6:
        return False
    ranges = [(c["high"] - c["low"]) for c in candles[-6:-1]]
    avg_range = sum(ranges) / len(ranges)
    last_range = candles[-1]["high"] - candles[-1]["low"]
    return last_range < avg_range * 0.6

# ======================
# NDS – Displacement
# ======================
def displacement(candles):
    if len(candles) < 2:
        return None
    last = candles[-1]
    prev = candles[-2]

    body = abs(last["close"] - last["open"])
    full = last["high"] - last["low"]

    if full == 0:
        return None

    strength = body / full

    if strength < 0.7:
        return None

    if last["close"] > prev["high"]:
        return "LONG"
    if last["close"] < prev["low"]:
        return "SHORT"

    return None

# ======================
# ساخت سیگنال NDS
# ======================
def nds_signal():
    candles = get_klines()
    if not candles:
        return None

    if not is_compression(candles):
        return None

    side = displacement(candles)
    if not side:
        return None

    last = candles[-1]
    base = candles[-6:-1]

    if side == "LONG":
        entry = last["close"]
        sl = min(c["low"] for c in base)
        tp = entry + (entry - sl) * 2
    else:
        entry = last["close"]
        sl = max(c["high"] for c in base)
        tp = entry - (sl - entry) * 2

    return side, entry, sl, tp

# ======================
# محدودیت ۳ سیگنال در روز
# ======================
signals = {}

def can_send():
    today = date.today().isoformat()
    signals.setdefault(today, 0)
    if signals[today] >= 3:
        return False
    signals[today] += 1
    return True

# ======================
# UI – دکمه استارت
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📊 تحلیل NDS BTC", callback_data="nds")]]
    await update.message.reply_text(
        "ربات NDS فعال است 👇",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def nds_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not can_send():
        await query.message.reply_text("⛔️ سقف ۳ سیگنال امروز پر شده")
        return

    signal = nds_signal()
    if not signal:
        await query.message.reply_text("⏸ فعلاً Displacement معتبر نداریم")
        return

    side, entry, sl, tp = signal
    await query.message.reply_text(
        f"""
📊 BTCUSDT – NDS
🕒 TF: {TF}

{'🟢 LONG' if side == 'LONG' else '🔴 SHORT'}

🎯 Entry: {entry:.2f}
🛑 SL: {sl:.2f}
💰 TP: {tp:.2f}

⚠️ فقط تحلیل – تصمیم با خودت
"""
    )

# ======================
# Main
# ======================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(nds_button))
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_server).start()
    main()