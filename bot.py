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
bias_alerts = {}
CHAT_ID = None

# =========================
# ===== ADDED =====
# Persistent files (safe)
# =========================
BIAS_STATE_FILE = "bias_state.json"
SIGNAL_LOG_FILE = "signal_log.json"
RESTART_LOG_FILE = "restart_log.json"

# =========================
# VIP STORAGE (SAFE)
# =========================
VIP_FILE = "vip_users.json"
VIP_USERS = set()
ADMIN_ID = None

def load_vips():
    global VIP_USERS, ADMIN_ID
    if os.path.exists(VIP_FILE):
        with open(VIP_FILE, "r") as f:
            data = json.load(f)
            VIP_USERS = set(data.get("vips", []))
            ADMIN_ID = data.get("admin")

def save_vips():
    with open(VIP_FILE, "w") as f:
        json.dump({
            "admin": ADMIN_ID,
            "vips": list(VIP_USERS)
        }, f)

load_vips()

# =========================
# ===== ADDED =====
# Safe JSON helpers
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
# Get Candles (MEXC)
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
# NDS CORE LOGIC (UNCHANGED)
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
# Auto Signal (ONLY ADDITIONS)
# =========================
async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    bias_state = load_json(BIAS_STATE_FILE, {})
    logs = load_json(SIGNAL_LOG_FILE, [])

    for chat_id in VIP_USERS:
        for interval in ["15m", "30m", "1h"]:
            candles = get_klines(interval)
            if not candles or not compression(candles):
                continue

            bias = early_bias(candles)
            if not bias:
                continue

            # ===== ADDED =====
            # Bias change alert (persistent)
            prev_bias = bias_state.get(interval)
            if prev_bias and prev_bias != bias:
                iran_time = datetime.utcnow() + timedelta(hours=3, minutes=30)
                time_str = iran_time.strftime("%Y-%m-%d | %H:%M")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"""
🔔 BTC BIAS CHANGE ALERT

TF: {interval}
Previous: {prev_bias}
Current: {bias}
🕒 Time (IR): {time_str}
"""
                )
            bias_state[interval] = bias
            save_json(BIAS_STATE_FILE, bias_state)

            # ⏰ Iran Time
            iran_time = datetime.utcnow() + timedelta(hours=3, minutes=30)
            time_str = iran_time.strftime("%Y-%m-%d | %H:%M")

            if not displacement(candles, bias):
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

            # ===== ADDED =====
            # Grade A/B/C
            grade = "C"
            score = 0
            if confidence >= 75:
                score += 1
            if interval == "1h":
                score += 1
            if potential >= 1500:
                score += 1

            if score == 3:
                grade = "A"
            elif score == 2:
                grade = "B"

            # ===== ADDED =====
            # Log signal
            logs.append({
                "time": time_str,
                "tf": interval,
                "bias": bias,
                "grade": grade,
                "entry": round(entry, 2)
            })
            save_json(SIGNAL_LOG_FILE, logs[-200:])

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"""
🚨 BTC NDS PRO SIGNAL ({grade})

Market Bias: {bias}
TF: {interval}
🕒 Time (IR): {time_str}

📍 Entry: {entry:.2f}
🛑 SL: {sl:.2f}
🎯 TP: {tp:.2f}

🎯 Confidence: {confidence}%
⚠️ تصمیم نهایی با شما
"""
            )

# =========================
# Commands (UNCHANGED)
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_ID
    cid = update.effective_chat.id

    if ADMIN_ID is None:
        ADMIN_ID = cid
        VIP_USERS.add(cid)
        save_vips()
        await update.message.reply_text("👑 شما ادمین شدید")
        return

    if cid in VIP_USERS:
        await update.message.reply_text("✅ دسترسی VIP فعال است")
    else:
        await update.message.reply_text("⏳ در انتظار تأیید ادمین")

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        return
    uid = int(context.args[0])
    VIP_USERS.add(uid)
    save_vips()
    await update.message.reply_text(f"✅ {uid} VIP شد")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        return
    uid = int(context.args[0])
    VIP_USERS.discard(uid)
    save_vips()
    await update.message.reply_text(f"❌ {uid} حذف شد")

async def viplist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        return
    text = "📋 VIP USERS:\n" + "\n".join(str(x) for x in VIP_USERS)
    await update.message.reply_text(text)

async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Chat ID: {update.effective_chat.id}")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in VIP_USERS:
        await update.message.reply_text("❌ دسترسی VIP نداری")
        return

    ok = []
    for interval in ["15m", "30m", "1h"]:
        candles = get_klines(interval)
        if not candles:
            ok.append(f"{interval}: ❌ خطا")
        else:
            ok.append(f"{interval}: ✅ Bias = {early_bias(candles)} | Close = {candles[-1]['close']:.2f}")

    await update.message.reply_text("\n".join(ok))

# =========================
# Main (UNTOUCHED)
# =========================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("viplist", viplist))
    app.add_handler(CommandHandler("id", show_id))
    app.add_handler(CommandHandler("test", test))

    app.job_queue.run_repeating(auto_signal, interval=180, first=20)
    app.run_polling()

if __name__ == "__main__":
    # ===== ADDED =====
    # Restart log only (no message, safe)
    restarts = load_json(RESTART_LOG_FILE, [])
    restarts.append({
        "time": (datetime.utcnow() + timedelta(hours=3, minutes=30)).strftime("%Y-%m-%d | %H:%M")
    })
    save_json(RESTART_LOG_FILE, restarts[-50:])

    main()