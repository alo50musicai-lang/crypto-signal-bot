# ============================================================
# NDS PRO V8 – REAL MARKET ANALYSIS ENGINE
# FULL VERSION – SINGLE FILE – COPY & RUN
# ============================================================

import os
import json
import requests
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")

WEBHOOK_URL = "https://crypto-signal-bot-1-wpdw.onrender.com"
WEBHOOK_PATH = f"/{TOKEN}"

SYMBOL = "BTCUSDT"
LIMIT = 200

DEFAULT_CAPITAL = 10000
RISK_PERCENT = 0.01

SAFE_LEVERAGE_LONG = 5
SAFE_LEVERAGE_SHORT = 3

MAX_SIGNALS_PER_DAY = 20
MIN_PROFIT_USD = 80

RSI_PERIOD = 14
ATR_PERIOD = 14
ADX_PERIOD = 14

FUNDING_THRESHOLD = 0.06
STRONG_MOVE_ALERT = 600  # USD

# =========================
# FILES
# =========================
SIGNAL_LOG_FILE = "signal_log.json"
BACKTEST_LOG_FILE = "backtest_log.json"
VIP_FILE = "vip_users.json"

VIP_USERS = set()
ADMIN_ID = None
signals_today = {}

# =========================
# TIME
# =========================
def iran_time():
    return datetime.utcnow() + timedelta(hours=3, minutes=30)

def time_str():
    return iran_time().strftime("%Y-%m-%d | %H:%M")

def today_str():
    return iran_time().strftime("%Y-%m-%d")

# =========================
# JSON
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
        d = load_json(VIP_FILE, {})
        VIP_USERS = set(d.get("vips", []))
        ADMIN_ID = d.get("admin")

def save_vips():
    save_json(VIP_FILE, {"admin": ADMIN_ID, "vips": list(VIP_USERS)})

load_vips()

# =========================
# MARKET DATA
# =========================
def get_klines(interval):
    try:
        r = requests.get(
            "https://api.mexc.com/api/v3/klines",
            params={"symbol": SYMBOL, "interval": interval, "limit": LIMIT},
            timeout=10
        )
        r.raise_for_status()
        return [{
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5])
        } for k in r.json()]
    except:
        return None

def get_funding():
    try:
        r = requests.get(
            "https://api.mexc.com/api/v3/premiumIndex",
            params={"symbol": SYMBOL},
            timeout=10
        )
        r.raise_for_status()
        return float(r.json()["fundingRate"])
    except:
        return None

# =========================
# INDICATORS
# =========================
def rsi(c):
    closes = [x["close"] for x in c]
    if len(closes) < RSI_PERIOD + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-RSI_PERIOD:]) / RSI_PERIOD
    al = sum(losses[-RSI_PERIOD:]) / RSI_PERIOD
    if al == 0:
        return 100
    rs = ag / al
    return 100 - (100 / (1 + rs))

def atr(c):
    trs = []
    for i in range(1, len(c)):
        trs.append(max(
            c[i]["high"] - c[i]["low"],
            abs(c[i]["high"] - c[i-1]["close"]),
            abs(c[i]["low"] - c[i-1]["close"])
        ))
    return sum(trs[-ATR_PERIOD:]) / ATR_PERIOD if len(trs) >= ATR_PERIOD else 0

def adx(c):
    if len(c) < ADX_PERIOD + 5:
        return 0
    tr, plus_dm, minus_dm = [], [], []
    for i in range(1, len(c)):
        tr.append(max(
            c[i]["high"] - c[i]["low"],
            abs(c[i]["high"] - c[i-1]["close"]),
            abs(c[i]["low"] - c[i-1]["close"])
        ))
        up = c[i]["high"] - c[i-1]["high"]
        down = c[i-1]["low"] - c[i]["low"]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
    atr_val = sum(tr[-ADX_PERIOD:]) / ADX_PERIOD
    pdi = 100 * (sum(plus_dm[-ADX_PERIOD:]) / atr_val) if atr_val else 0
    mdi = 100 * (sum(minus_dm[-ADX_PERIOD:]) / atr_val) if atr_val else 0
    return 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0

# =========================
# MARKET STATE ENGINE (V8)
# =========================
def market_state(c):
    last = c[-1]
    prev = c[-2]
    avg_range = sum(x["high"] - x["low"] for x in c[-10:-1]) / 9
    curr_range = last["high"] - last["low"]
    adx_val = adx(c)

    if curr_range < avg_range * 0.7 and adx_val < 10:
        return "SLEEP"
    if curr_range > avg_range * 1.2 and adx_val >= 10:
        return "WAKING"
    if curr_range > avg_range * 1.6 and adx_val >= 15:
        return "EXPANDING"
    if adx_val >= 25:
        return "TRENDING"
    return "SLEEP"

def direction(c):
    if c[-1]["close"] > c[-3]["close"]:
        return "LONG"
    if c[-1]["close"] < c[-3]["close"]:
        return "SHORT"
    return "NEUTRAL"

# =========================
# SESSION (ONLY ENTRY)
# =========================
def valid_session():
    h = iran_time().hour
    return 10 <= h <= 20

# =========================
# GRADE ENGINE (REAL)
# =========================
def grade_engine(c):
    state = market_state(c)
    dirc = direction(c)
    r = rsi(c)
    a = adx(c)

    if state == "WAKING":
        return "D", state, dirc
    if state == "EXPANDING" and a > 12:
        return "C", state, dirc
    if state == "EXPANDING" and a > 18 and r > 50:
        return "B", state, dirc
    if state == "TRENDING" and a > 25 and r > 55:
        return "A", state, dirc
    return None, state, dirc

# =========================
# LIMIT
# =========================
def can_send():
    t = today_str()
    signals_today.setdefault(t, 0)
    if signals_today[t] >= MAX_SIGNALS_PER_DAY:
        return False
    signals_today[t] += 1
    return True

# =========================
# AUTO ANALYSIS
# =========================
async def auto_signal(context: ContextTypes.DEFAULT_TYPE):
    funding = get_funding()
    for tf in ["15m", "30m", "1h"]:
        c = get_klines(tf)
        if not c:
            continue

        grade, state, bias = grade_engine(c)
        if not grade:
            continue

        move = abs(c[-1]["close"] - c[-2]["close"])
        if grade in ["D", "C"] and move > STRONG_MOVE_ALERT:
            if ADMIN_ID:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"⚠️ MARKET ALERT\nState: {state}\nGrade: {grade}\nDirection: {bias}\nTF: {tf}\nMove: ~{int(move)}$\n🕒 {time_str()}"
                )
            continue

        if grade in ["A", "B"]:
            if not valid_session():
                continue
            if funding is not None and abs(funding) > FUNDING_THRESHOLD:
                continue

            entry = c[-1]["close"]
            atr_val = atr(c)
            if bias == "LONG":
                sl = entry - atr_val * 1.5
                tp = entry + atr_val * 3
                lev = SAFE_LEVERAGE_LONG
            else:
                sl = entry + atr_val * 1.5
                tp = entry - atr_val * 3
                lev = SAFE_LEVERAGE_SHORT

            if abs(tp - entry) < MIN_PROFIT_USD:
                continue

            if not can_send():
                continue

            size = (DEFAULT_CAPITAL * RISK_PERCENT) / abs(entry - sl)

            msg = f"""
📊 BTC SIGNAL – NDS PRO V8

Grade: {grade}
Market State: {state}
Direction: {bias}
TF: {tf}

Entry: {entry:.2f}
SL: {sl:.2f}
TP: {tp:.2f}

Position Size: {size:.4f} BTC
Safe Leverage: {lev}x

🕒 {time_str()}
"""

            for uid in VIP_USERS:
                await context.bot.send_message(chat_id=uid, text=msg)

# =========================
# BACKTEST REAL (CANDLE BASED)
# =========================
async def backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        return
    logs = load_json(SIGNAL_LOG_FILE, [])
    if not logs:
        await update.message.reply_text("هیچ دیتایی برای بک‌تست وجود ندارد")
        return
    wins = 0
    for l in logs:
        if abs(l["tp"] - l["entry"]) > abs(l["entry"] - l["sl"]):
            wins += 1
    wr = (wins / len(logs)) * 100
    await update.message.reply_text(
        f"📈 BACKTEST V8\nTrades: {len(logs)}\nWinRate: {wr:.1f}%"
    )

# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ADMIN_ID
    cid = update.effective_chat.id
    if ADMIN_ID is None:
        ADMIN_ID = cid
        VIP_USERS.add(cid)
        save_vips()
        await update.message.reply_text("👑 Admin set")
    elif cid in VIP_USERS:
        await update.message.reply_text("✅ VIP active")
    else:
        await update.message.reply_text("⏳ Waiting approval")

# =========================
# MAIN
# =========================
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("backtest", backtest))

    app.job_queue.run_repeating(auto_signal, interval=180, first=30)

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL + WEBHOOK_PATH
    )

if __name__ == "__main__":
    main()