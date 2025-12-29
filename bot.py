import os
import threading
import requests
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================
# Fake Web Server (Render)
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

MAX_SIGNALS_PER_DAY = 4
MIN_PROFIT_USD = 700   # فقط سیگنال‌های بزرگ

signals_today = {}
CHAT_ID = None

# =========================
# Get Candles (MEXC v3 - FIXED)
# =========================
def get_klines(interval):
    try:
        url = "https://api.mexc.com/api/v3/klines"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        params = {
            "symbol": SYMBOL,
            "interval": interval,
            "limit": LIMIT
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()

        return [{
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
        } for k in data]

    except Exception as e:
        print("❌ Candle Error:", e)
        return None

# =========================
# NDS CORE LOGIC
# =========================
def compression(candles):
    if len(candles) < 6:
        return False
    ranges = [(c["high"] - c["low"]) for c in candles[-6:-1]]
    avg_range = sum(ranges) / len(ranges)
    last_range = candles[-1]["high"] - candles[-1]["low"]
    return last_range < avg_range * 0.7

def early_bias(candles):
    lows = [c["low"] for c in candles[-4:]]
    highs = [c["high"] for c in candles[-4:]]

    if lows[-1] > lows[-2] > lows[-3]:
        return "LONG"
    if highs[-1] < highs[-2] < highs[-3]:
        return "SHORT"
    return None

def displacement(candles, bias):
    last = candles[-1]
    prev = candles[-2]

    body = abs(last["close"] - last["open"])
    full = last["high"] - last["low"]
    if full == 0:
        return False

    strength = body / full

    if bias == "LONG" and last["close"] > prev["high"] and strength > 0.55:
        return True
    if bias == "SHORT" and last["close"] < prev["low"] and strength > 0.55:
        return True
    return False

def confidence_score(candles, bias, potential):
    score = 0
    if compression(candles):
        score += 25
    if bias:
        score += 25
    if potential > 1000:
        score += 25
    if potential > 1500:
        score += 25
    return min(score, 95)

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
# Auto Signal (Option C +700)
# =========================
async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    if CHAT_ID is None:
        return

    for interval in ["15m", "30m", "1h"]:
        candles = get_klines(interval)
        if not candles or not compression(candles):
            continue

        bias = early_bias(candles)
        if not bias:
            continue

        # Bias Alert (قبل از ورود)
        if not displacement(candles, bias):
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"""
📊 BTC NDS BIAS ALERT

Bias: {bias}
TF: {interval}

⏳ بازار در حال ساخت روند
⚠️ هنوز ورود نداریم
"""
            )
            continue

        last = candles[-1]
        prev = candles[-2]

        entry = last["close"]
        sl = prev["low"] if bias == "LONG" else prev["high"]
        risk = abs(entry - sl)

        tp = entry + risk * 2.5 if bias == "LONG" else entry - risk * 2.5
        potential = abs(tp - entry)

        if potential < MIN_PROFIT_USD or not can_send():
            continue

        confidence = confidence_score(candles, bias, potential)

        text = f"""
🚨 BTC NDS PRO SIGNAL

📊 Direction: {bias}
⏱ TF: {interval}

🎯 Entry: {entry:.2f}
🛑 SL: {sl:.2f}
💰 TP: {tp:.2f}

📈 Potential: {potential:.0f}$+
🎯 Confidence: {confidence}%

⚠️ NDS فازی لاجیک – سیگنال قدرتمند
"""
        await context.bot.send_message(chat_id=CHAT_ID, text=text)

# =========================
# Commands
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    CHAT_ID = update.effective_chat.id
    await update.message.reply_text(
        "🤖 ربات NDS حرفه‌ای فعال شد\n"
        "فقط سیگنال‌های بزرگ (+700$)\n"
        "تشخیص جهت قبل از ورود"
    )

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok = []
    for interval in ["15m", "30m", "1h"]:
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
        interval=180,
        first=20
    )

    app.run_polling()

if __name__ == "__main__":
    main()