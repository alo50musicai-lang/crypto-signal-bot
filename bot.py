import os
import json
import requests
from datetime import date, datetime, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("TELEGRAM_TOKEN")

WEBHOOK_URL = "https://crypto-signal-bot-1-wpdw.onrender.com"
WEBHOOK_PATH = f"/{TOKEN}"

SYMBOL = "BTCUSDT"
LIMIT = 120
MAX_SIGNALS_PER_DAY = 3  # OPTIMIZED: Reduced to 3 for higher quality
MIN_PROFIT_USD = 700
STRONG_MOVE_USD = 800
RSI_PERIOD = 14  # OPTIMIZED: For RSI filter
VOLUME_MULTIPLIER = 1.5  # OPTIMIZED: Volume > avg * this
ATR_PERIOD = 14  # OPTIMIZED: For dynamic SL/TP

# =========================
# PERSISTENT FILES
# =========================
BIAS_STATE_FILE = "bias_state.json"
SIGNAL_LOG_FILE = "signal_log.json"
STRONG_MOVE_LOG_FILE = "strong_move_log.json"
RESTART_LOG_FILE = "restart_log.json"
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
# JSON HELPERS
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
        data = r.json()
        return [{
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5])  # OPTIMIZED: Added volume
        } for k in data]
    except:
        return None

# =========================
# NDS CORE
# =========================
def compression(c):
    ranges = [(x["high"] - x["low"]) for x in c[-6:-1]]
    return (c[-1]["high"] - c[-1]["low"]) < (sum(ranges)/len(ranges)) * 0.7

def early_bias(c):
    lows = [x["low"] for x in c[-4:]]
    highs = [x["high"] for x in c[-4:]]
    if lows[-1] > lows[-2] > lows[-3]:
        return "LONG"
    if highs[-1] < highs[-2] < highs[-3]:
        return "SHORT"
    return None

def displacement(c, bias):
    last, prev = c[-1], c[-2]
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
    c = get_klines("4h")
    if not c:
        return None
    return early_bias(c)

def valid_session():
    h = iran_time().hour
    return (10 <= h <= 14) or (16 <= h <= 20)

def liquidity_sweep(c, bias):
    if bias == "LONG":
        return c[-1]["low"] < min(x["low"] for x in c[-6:-1])
    if bias == "SHORT":
        return c[-1]["high"] > max(x["high"] for x in c[-6:-1])
    return False

def detect_fvg(c, bias):
    c1, c3 = c[-3], c[-1]
    if bias == "LONG" and c1["high"] < c3["low"]:
        return (c1["high"], c3["low"])
    if bias == "SHORT" and c1["low"] > c3["high"]:
        return (c3["high"], c1["low"])
    return None

# OPTIMIZED: New filters
def calculate_rsi(c, period=RSI_PERIOD):
    closes = [x["close"] for x in c]
    delta = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gain = [d if d > 0 else 0 for d in delta]
    loss = [-d if d < 0 else 0 for d in delta]
    avg_gain = sum(gain[-period:]) / period
    avg_loss = sum(loss[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def volume_filter(c):
    volumes = [x["volume"] for x in c[-21:-1]]  # 20 previous
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    return c[-1]["volume"] > avg_vol * VOLUME_MULTIPLIER

def calculate_atr(c, period=ATR_PERIOD):
    trs = []
    for i in range(1, len(c)):
        tr = max(c[i]["high"] - c[i]["low"], abs(c[i]["high"] - c[i-1]["close"]), abs(c[i]["low"] - c[i-1]["close"]))
        trs.append(tr)
    avg_tr = sum(trs[-period:]) / period if len(trs) >= period else 0
    return avg_tr

def confidence_score(p, rsi_conf=0):
    s = 25 + rsi_conf  # OPTIMIZED: Add RSI to score
    if p > 1000: s += 25
    if p > 1500: s += 25
    if p > 2000: s += 20
    return min(s, 95)

# =========================
# LIMIT
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

    logs = load_json(SIGNAL_LOG_FILE, [])
    strong_logs = load_json(STRONG_MOVE_LOG_FILE, [])

    for chat_id in VIP_USERS:
        for tf in ["15m", "30m", "1h"]:
            c = get_klines(tf)
            if not c or not valid_session():
                continue

            bias = early_bias(c)
            if not bias:
                continue

            move = abs(c[-1]["close"] - c[-2]["open"])
            has_disp = displacement(c, bias)
            has_liq = liquidity_sweep(c, bias)
            fvg = detect_fvg(c, bias)

            # OPTIMIZED: New checks
            rsi = calculate_rsi(c)
            rsi_conf = 10 if (bias == "LONG" and rsi > 55) or (bias == "SHORT" and rsi < 45) else 0
            if rsi_conf == 0 or not volume_filter(c):
                continue  # Skip if no RSI/volume confirm

            atr = calculate_atr(c)

            if (
                ADMIN_ID
                and has_disp
                and move >= STRONG_MOVE_USD
                and (bias != HTF or not has_liq or not fvg)
            ):
                strong_logs.append({
                    "date": today_str(),
                    "tf": tf,
                    "bias": bias
                })
                save_json(STRONG_MOVE_LOG_FILE, strong_logs[-500:])

                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"""
⚠️ STRONG MOVE – NO ENTRY

Direction: {bias}
TF: {tf}
Move: ~{int(move)} USDT
🕒 {time_str()}
"""
                )

            if bias != HTF:
                continue
            if not compression(c):
                continue
            if not has_liq:
                continue
            if not has_disp:
                continue
            if not fvg:
                continue
            if not can_send():
                continue

            entry = sum(fvg) / 2
            risk = abs(fvg[1] - fvg[0]) + atr * 0.5  # OPTIMIZED: Add ATR to risk

            if bias == "LONG":
                sl = fvg[0] - risk * 0.2
                tp = entry + risk * 3
                title = "🟢🟢🟢 BTC LONG – NDS PRO V2"
            else:
                sl = fvg[1] + risk * 0.2
                tp = entry - risk * 3
                title = "🔴🔴🔴 BTC SHORT – NDS PRO V2"

            potential = abs(tp - entry)
            if potential < MIN_PROFIT_USD:
                continue

            conf = confidence_score(potential, rsi_conf)
            grade = "A" if conf >= 80 else "B" if conf >= 60 else "C"

            logs.append({
                "date": today_str(),
                "grade": grade
            })
            save_json(SIGNAL_LOG_FILE, logs[-500:])

            receivers = set(VIP_USERS)
            if ADMIN_ID:
                receivers.add(ADMIN_ID)

            for rid in receivers:
                await context.bot.send_message(
                    chat_id=rid,
                    text=f"""
{title}

TF: {tf}
🕒 {time_str()}

Entry: {entry:.2f}
SL: {sl:.2f}
TP: {tp:.2f}

Confidence: {conf}%
Grade: {grade}
⚠️ تصمیم نهایی با شما
"""
                )

# =========================
# DAILY SUMMARY (ADMIN)
# =========================
async def daily_summary(context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID:
        return

    today = today_str()
    logs = load_json(SIGNAL_LOG_FILE, [])
    strong_logs = load_json(STRONG_MOVE_LOG_FILE, [])

    today_signals = [x for x in logs if x.get("date") == today]
    today_strong = [x for x in strong_logs if x.get("date") == today]

    if len(today_signals) == 0 and len(today_strong) == 0:
        return

    a = sum(1 for x in today_signals if x.get("grade") == "A")
    b = sum(1 for x in today_signals if x.get("grade") == "B")
    c = sum(1 for x in today_signals if x.get("grade") == "C")

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"""
📊 DAILY SUMMARY – BTC NDS PRO V2

Date: {today}

Signals:
• Total: {len(today_signals)}
• A: {a} | B: {b} | C: {c}

Strong Moves (No Entry): {len(today_strong)}

🕒 Generated at: {time_str()}
"""
    )

# =========================
# DAILY SUMMARY (MANUAL)
# =========================
async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("❌ فقط ادمین")
        return

    today = today_str()
    logs = load_json(SIGNAL_LOG_FILE, [])
    strong_logs = load_json(STRONG_MOVE_LOG_FILE, [])

    today_signals = [x for x in logs if x.get("date") == today]
    today_strong = [x for x in strong_logs if x.get("date") == today]

    a = sum(1 for x in today_signals if x.get("grade") == "A")
    b = sum(1 for x in today_signals if x.get("grade") == "B")
    c = sum(1 for x in today_signals if x.get("grade") == "C")

    await update.message.reply_text(
        f"""
📊 DAILY SUMMARY – BTC NDS PRO V2 (Manual)

Date: {today}

Signals:
• Total: {len(today_signals)}
• A: {a} | B: {b} | C: {c}

Strong Moves (No Entry): {len(today_strong)}

🕒 Generated at: {time_str()}
"""
    )

# =========================
# HEARTBEAT (ADMIN – 3H)
# =========================
async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🟢 BOT ALIVE – NDS PRO V2\n🕒 {time_str()}\nStatus: Running"
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

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = requests.get(
            "https://api.mexc.com/api/v3/ticker/24hr",
            params={"symbol": "BTCUSDT"},
            timeout=10
        )
        r.raise_for_status()
        d = r.json()
        price = float(d["lastPrice"])
        change = float(d["priceChangePercent"])
    except:
        await update.message.reply_text("❌ خطا در دریافت قیمت")
        return

    sign = "🟢 +" if change >= 0 else "🔴 "
    await update.message.reply_text(
        f"""
💰 BTC LIVE PRICE

Price: {price:,.2f} USDT
24h Change: {sign}{change:.2f}%
🕒 {time_str()}
Source: MEXC
"""
    )

async def high(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = requests.get(
            "https://api.mexc.com/api/v3/ticker/24hr",
            params={"symbol": "BTCUSDT"},
            timeout=10
        )
        r.raise_for_status()
        d = r.json()
        high_price = float(d["highPrice"])
    except:
        await update.message.reply_text("❌ خطا در دریافت High")
        return

    await update.message.reply_text(
        f"""
📈 BTC DAILY HIGH

High Today: {high_price:,.2f} USDT
🕒 {time_str()}
Source: MEXC
"""
    )

async def ath(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = requests.get(
            "https://api.mexc.com/api/v3/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1d",
                "limit": 1000
            },
            timeout=15
        )
        r.raise_for_status()
        data = r.json()

        ath_price = 0
        ath_time = None

        for c in data:
            high = float(c[2])
            if high > ath_price:
                ath_price = high
                ath_time = int(c[0])

        ath_datetime = datetime.utcfromtimestamp(ath_time / 1000) + timedelta(hours=3, minutes=30)

    except:
        await update.message.reply_text("❌ خطا در دریافت ATH")
        return

    await update.message.reply_text(
        f"""
🚀 BTC ALL TIME HIGH

ATH: {ath_price:,.2f} USDT
📅 Date: {ath_datetime.strftime('%Y-%m-%d')}
🕒 Time (IR): {ath_datetime.strftime('%H:%M')}
Source: MEXC
"""
    )

# =========================
# MAIN
# =========================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("viplist", viplist))
    app.add_handler(CommandHandler("id", show_id))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("high", high))
    app.add_handler(CommandHandler("ath", ath))
    app.add_handler(CommandHandler("summary", summary))
    
    app.job_queue.run_repeating(auto_signal, interval=180, first=30)
    app.job_queue.run_repeating(heartbeat, interval=10800, first=60)
    app.job_queue.run_daily(daily_summary, time=datetime.utcnow().replace(hour=20, minute=30, second=0))

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 10000)),
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL + WEBHOOK_PATH
    )

if __name__ == "__main__":
    restarts = load_json(RESTART_LOG_FILE, [])
    restarts.append({"time": time_str()})
    save_json(RESTART_LOG_FILE, restarts[-50:])
    main()