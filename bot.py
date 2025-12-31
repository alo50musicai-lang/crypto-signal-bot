import os
import json
import threading
import requests
from datetime import date, datetime, timedelta
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
MIN_PROFIT_USD = 700

signals_today = {}
CHAT_ID = None

# =========================
# Persistent Files
# =========================
BIAS_STATE_FILE = "bias_state.json"
SIGNAL_LOG_FILE = "signal_log.json"
RESTART_LOG_FILE = "restart_log.json"
VIP_FILE = "vip_users.json"

VIP_USERS = set()
ADMIN_ID = None

# =========================
# JSON Helpers
# =========================
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# =========================
# VIP
# =========================
def load_vips():
    global VIP_USERS, ADMIN_ID
    if os.path.exists(VIP_FILE):
        with open(VIP_FILE, "r") as f:
            data = json.load(f)
            VIP_USERS = set(data.get("vips", []))
            ADMIN_ID = data.get("admin")

def save_vips():
    with open(VIP_FILE, "w") as f:
        json.dump({"admin": ADMIN_ID, "vips": list(VIP_USERS)}, f)

load_vips()

# =========================
# Market Data
# =========================
def get_klines(interval):
    try:
        r = requests.get(
            "https://api.mexc.com/api/v3/klines",
            params={"symbol": SYMBOL, "interval": interval, "limit": LIMIT},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        return [{
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4])
        } for k in data]
    except:
        return None

# =========================
# NDS CORE
# =========================
def compression(candles):
    ranges = [(c["high"] - c["low"]) for c in candles[-6:-1]]
    return (candles[-1]["high"] - candles[-1]["low"]) < (sum(ranges)/len(ranges))*0.7

def early_bias(candles):
    lows = [c["low"] for c in candles[-4:]]
    highs = [c["high"] for c in candles[-4:]]
    if lows[-1] > lows[-2] > lows[-3]:
        return "LONG"
    if highs[-1] < highs[-2] < highs[-3]:
        return "SHORT"
    return None

def displacement(candles, bias):
    last, prev = candles[-1], candles[-2]
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

# =========================
# PRO ADDITIONS
# =========================
def htf_bias():
    candles = get_klines("4h")
    if not candles:
        return None
    return early_bias(candles)

def valid_session():
    hour = (datetime.utcnow() + timedelta(hours=3, minutes=30)).hour
    return (10 <= hour <= 14) or (16 <= hour <= 20)

def liquidity_sweep(candles, bias):
    if bias == "LONG":
        return candles[-1]["low"] < min(c["low"] for c in candles[-6:-1])
    if bias == "SHORT":
        return candles[-1]["high"] > max(c["high"] for c in candles[-6:-1])
    return False

def detect_fvg(candles, bias):
    c1, _, c3 = candles[-3], candles[-2], candles[-1]
    if bias == "LONG" and c1["high"] < c3["low"]:
        return (c1["high"], c3["low"])
    if bias == "SHORT" and c1["low"] > c3["high"]:
        return (c3["high"], c1["low"])
    return None

def confidence_score(potential):
    score = 25
    if potential > 1000: score += 25
    if potential > 1500: score += 25
    if potential > 2000: score += 20
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
# AUTO SIGNAL
# =========================
async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    HTF = htf_bias()
    if HTF is None:
        return

    bias_state = load_json(BIAS_STATE_FILE, {})
    logs = load_json(SIGNAL_LOG_FILE, [])

    for chat_id in VIP_USERS:
        for interval in ["15m", "30m", "1h"]:
            candles = get_klines(interval)
            if not candles or not valid_session():
                continue

            bias = early_bias(candles)
            if not bias or bias != HTF:
                continue

            prev_bias = bias_state.get(interval)
            if prev_bias and prev_bias != bias:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔔 BIAS CHANGE\nTF:{interval}\n{prev_bias} ➜ {bias}"
                )
            bias_state[interval] = bias
            save_json(BIAS_STATE_FILE, bias_state)

            if not compression(candles):
                continue
            if not liquidity_sweep(candles, bias):
                continue
            if not displacement(candles, bias):
                continue

            fvg = detect_fvg(candles, bias)
            if not fvg:
                continue

            entry = sum(fvg) / 2
            risk = abs(fvg[1] - fvg[0])

            if bias == "LONG":
                sl = fvg[0] - risk * 0.2
                tp = entry + risk * 3
                title = "🟢🟢🟢 BTC LONG – NDS PRO"
            else:
                sl = fvg[1] + risk * 0.2
                tp = entry - risk * 3
                title = "🔴🔴🔴 BTC SHORT – NDS PRO"

            potential = abs(tp - entry)
            if potential < MIN_PROFIT_USD or not can_send():
                continue

            confidence = confidence_score(potential)
            grade = "A" if confidence >= 80 else "B" if confidence >= 60 else "C"

            logs.append({"tf": interval, "bias": bias, "entry": entry})
            save_json(SIGNAL_LOG_FILE, logs[-200:])

            iran_time = (datetime.utcnow() + timedelta(hours=3, minutes=30)).strftime("%Y-%m-%d | %H:%M")

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"""
{title}

TF: {interval}
🕒 {iran_time}

Entry: {entry:.2f}
SL: {sl:.2f}
TP: {tp:.2f}

Confidence: {confidence}%
Grade: {grade}
⚠️ تصمیم نهایی با شما
"""
            )

# =========================
# Commands
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_ID
    cid = update.effective_chat.id
    if ADMIN_ID is None:
        ADMIN_ID = cid
        VIP_USERS.add(cid)
        save_vips()
        await update.message.reply_text("👑 شما ادمین شدید")
    elif cid in VIP_USERS:
        await update.message.reply_text("✅ VIP فعال است")
    else:
        await update.message.reply_text("⏳ در انتظار تایید")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id == ADMIN_ID:
        uid = int(context.args[0])
        VIP_USERS.add(uid)
        save_vips()
        await update.message.reply_text("✅ VIP شد")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id == ADMIN_ID:
        uid = int(context.args[0])
        VIP_USERS.discard(uid)
        save_vips()
        await update.message.reply_text("❌ حذف شد")

async def viplist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id == ADMIN_ID:
        await update.message.reply_text("\n".join(str(x) for x in VIP_USERS))

async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(str(update.effective_chat.id))

# =========================
# Main
# =========================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("viplist", viplist))
    app.add_handler(CommandHandler("id", show_id))
    app.job_queue.run_repeating(auto_signal, interval=180, first=20)
    app.run_polling()

if __name__ == "__main__":
    restarts = load_json(RESTART_LOG_FILE, [])
    restarts.append({"time": datetime.utcnow().isoformat()})
    save_json(RESTART_LOG_FILE, restarts[-50:])
    main()