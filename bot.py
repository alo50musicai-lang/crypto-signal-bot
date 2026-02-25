# =========================================
# BTC PRICE ACTION SIGNAL BOT – FULL FILE
# Version: V7.9 – Price Action
# =========================================

import os
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from math import fabs

import aiohttp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# =========================================
# CONFIG
# =========================================

BOT_VERSION = "V7.9 – PRICE ACTION"
MODE = "PRICE ACTION"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None

# اگر می‌خوای سیگنال‌ها برای چند VIP بره، اینجا chat_id ها رو بذار
# می‌تونی بعداً با /addvip و /rmvip هم مدیریت کنی
VIP_IDS_ENV = os.getenv("VIP_IDS", "")  # مثلا: "12345,67890"
VIP_IDS = set()
for part in VIP_IDS_ENV.split(","):
    part = part.strip()
    if part.isdigit():
        VIP_IDS.add(int(part))

SYMBOL = "BTCUSDT"
TZ = timezone.utc

BINANCE_FUTURES_URL = "https://fapi.binance.com"

WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # اگر خالی باشه → polling
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", "8000"))

# =========================================
# LOGGING
# =========================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =========================================
# UTILS
# =========================================

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def time_str(dt: datetime | None = None) -> str:
    if dt is None:
        dt = now_utc()
    return dt.astimezone(TZ).strftime("%Y-%m-%d | %H:%M")

# آمار روزانه
daily_stats = {
    "date": None,
    "signals": 0,
    "pa_breakouts": 0,
}

def reset_daily_stats_if_needed():
    today = now_utc().date()
    if daily_stats["date"] != today:
        daily_stats["date"] = today
        daily_stats["signals"] = 0
        daily_stats["pa_breakouts"] = 0

# =========================================
# HTTP SESSION & BINANCE
# =========================================

_session: aiohttp.ClientSession | None = None

async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session

async def fetch_binance_klines(symbol: str, interval: str, limit: int = 200):
    session = await get_session()
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    url = f"{BINANCE_FUTURES_URL}/fapi/v1/klines"
    try:
        async with session.get(url, params=params, timeout=10) as resp:
            if resp.status != 200:
                logger.warning(f"klines status: {resp.status}")
                return None
            return await resp.json()
    except Exception as e:
        logger.error(f"klines error: {e}")
        return None

async def fetch_last_price(symbol: str) -> float | None:
    session = await get_session()
    url = f"{BINANCE_FUTURES_URL}/fapi/v1/ticker/price"
    params = {"symbol": symbol}
    try:
        async with session.get(url, params=params, timeout=10) as resp:
            if resp.status != 200:
                logger.warning(f"price status: {resp.status}")
                return None
            data = await resp.json()
            return float(data.get("price"))
    except Exception as e:
        logger.error(f"price error: {e}")
        return None

# =========================================
# PRICE ACTION ANALYSIS
# =========================================

async def analyze_price_action_breakout() -> list[dict]:
    """
    تحلیل ساده پرایس اکشن:
    - تایم‌فریم 15m
    - پیدا کردن swing high / swing low
    - اگر قیمت آخرین swing high مهم را با 0.2% بشکند → LONG
    - اگر قیمت آخرین swing low مهم را با 0.2% بشکند → SHORT
    """

    klines = await fetch_binance_klines(SYMBOL, "15m", limit=60)
    if not klines or len(klines) < 20:
        return []

    candles = []
    for k in klines:
        candles.append({
            "open_time": k[0],
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
        })

    swing_highs = []
    swing_lows = []

    for i in range(2, len(candles) - 2):
        h = candles[i]["high"]
        if (
            h > candles[i-1]["high"]
            and h > candles[i-2]["high"]
            and h > candles[i+1]["high"]
            and h > candles[i+2]["high"]
        ):
            swing_highs.append((i, h))

        l = candles[i]["low"]
        if (
            l < candles[i-1]["low"]
            and l < candles[i-2]["low"]
            and l < candles[i+1]["low"]
            and l < candles[i+2]["low"]
        ):
            swing_lows.append((i, l))

    if not swing_highs and not swing_lows:
        return []

    last_candle = candles[-1]
    last_close = last_candle["close"]

    recent_high = swing_highs[-1][1] if swing_highs else None
    recent_low = swing_lows[-1][1] if swing_lows else None

    signals: list[dict] = []

    # Breakout بالا
    if recent_high and last_close > recent_high * 1.002:
        move_usd = last_close - recent_high
        signals.append({
            "symbol": SYMBOL,
            "direction": "LONG",
            "grade": "D-PA",
            "tf": "15m",
            "ref_level": recent_high,
            "close": last_close,
            "move_usd": move_usd,
        })

    # Breakout پایین
    if recent_low and last_close < recent_low * 0.998:
        move_usd = recent_low - last_close
        signals.append({
            "symbol": SYMBOL,
            "direction": "SHORT",
            "grade": "D-PA",
            "tf": "15m",
            "ref_level": recent_low,
            "close": last_close,
            "move_usd": move_usd,
        })

    return signals

# =========================================
# SIGNAL TEXT
# =========================================

def build_signal_text(sig: dict) -> str:
    symbol = sig["symbol"]
    direction = sig["direction"]
    grade = sig["grade"]
    tf = sig["tf"]
    ref_level = sig["ref_level"]
    close = sig["close"]
    move_usd = sig["move_usd"]

    if direction == "LONG":
        entry = round(ref_level, 1)
        sl = round(ref_level - move_usd * 0.8, 1)
        tp1 = round(close + move_usd * 0.8, 1)
        tp2 = round(close + move_usd * 1.4, 1)
    else:
        entry = round(ref_level, 1)
        sl = round(ref_level + move_usd * 0.8, 1)
        tp1 = round(close - move_usd * 0.8, 1)
        tp2 = round(close - move_usd * 1.4, 1)

    text = (
        f"📡 SIGNAL – {grade}\n"
        f"📌 {symbol} | {direction}\n"
        f"⏱ Timeframe: {tf}\n\n"
        f"📏 Break Level: {round(ref_level, 1)}\n"
        f"💰 Current Price: {round(close, 1)}\n"
        f"📈 Move: {round(move_usd, 1)} USD\n\n"
        f"💰 Entry: {entry}\n"
        f"🛡 SL: {sl}\n"
        f"🎯 TP1: {tp1}\n"
        f"🎯 TP2: {tp2}\n\n"
        f"⚙️ Mode: {MODE}\n"
        f"🕒 {time_str()}"
    )
    return text

# =========================================
# VIP MANAGEMENT
# =========================================

async def add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /addvip <chat_id>")
        return
    try:
        cid = int(context.args[0])
        VIP_IDS.add(cid)
        await update.message.reply_text(f"✅ VIP added: {cid}")
    except ValueError:
        await update.message.reply_text("chat_id باید عدد باشد.")

async def rm_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /rmvip <chat_id>")
        return
    try:
        cid = int(context.args[0])
        if cid in VIP_IDS:
            VIP_IDS.remove(cid)
            await update.message.reply_text(f"❌ VIP removed: {cid}")
        else:
            await update.message.reply_text("این chat_id در VIP نیست.")
    except ValueError:
        await update.message.reply_text("chat_id باید عدد باشد.")

async def vip_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        return
    if not VIP_IDS:
        await update.message.reply_text("هیچ VIP ثبت نشده.")
        return
    text = "📜 VIP LIST:\n" + "\n".join(f"- {cid}" for cid in VIP_IDS)
    await update.message.reply_text(text)

# =========================================
# COMMANDS
# =========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"سلام {user.first_name or ''} 👋\n\n"
        f"BTC SIGNAL BOT – {BOT_VERSION}\n"
        f"Mode: {MODE}\n\n"
        f"این ربات بر اساس شکست سقف/کف (Price Action Breakout) سیگنال می‌دهد."
    )
    await update.message.reply_text(text)

async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = await fetch_last_price(SYMBOL)
    if p is None:
        await update.message.reply_text("نتوانستم قیمت را بگیرم.")
        return
    await update.message.reply_text(f"💰 {SYMBOL}\nقیمت فعلی: {p:.1f} USDT\n🕒 {time_str()}")

async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_daily_stats_if_needed()
    text = (
        f"📊 DAILY SUMMARY – {BOT_VERSION}\n"
        f"Mode: {MODE}\n\n"
        f"Signals today: {daily_stats['signals']}\n"
        f"PA Breakouts: {daily_stats['pa_breakouts']}\n\n"
        f"🕒 {time_str()}"
    )
    await update.message.reply_text(text)

last_auto_signal_run: datetime | None = None
last_auto_signal_ok: bool = False

async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [f"Health – {BOT_VERSION}"]
    if last_auto_signal_run is None:
        lines.append("- auto_signal: not yet run")
    else:
        delta = now_utc() - last_auto_signal_run
        sec = int(delta.total_seconds())
        status = "OK" if last_auto_signal_ok else "ERROR"
        lines.append(f"- auto_signal {status} (last {sec} sec ago)")
    if WEBHOOK_URL:
        lines.append(f"- Webhook: {WEBHOOK_URL.rstrip('/') + WEBHOOK_PATH}")
    else:
        lines.append("- Webhook: disabled (polling mode)")
    lines.append(f"\n🕒 {time_str()}")
    await update.message.reply_text("\n".join(lines))

async def test_d1_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        return
    text = (
        f"🧪 TEST SIGNAL – D-PA (TEST)\n"
        f"📌 BTCUSDT | LONG\n"
        f"⏱ Timeframe: 15m\n\n"
        f"💰 Entry: 68000\n"
        f"🛡 SL: 67400\n"
        f"🎯 TP1: 68600\n"
        f"🎯 TP2: 69200\n\n"
        f"⚠️ این فقط یک تست برای ADMIN است.\n"
        f"🕒 {time_str()}"
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=text)

# =========================================
# AUTO SIGNAL
# =========================================

async def auto_signal_job(context: ContextTypes.DEFAULT_TYPE):
    global last_auto_signal_run, last_auto_signal_ok
    last_auto_signal_run = now_utc()
    reset_daily_stats_if_needed()

    try:
        signals = await analyze_price_action_breakout()
        if not signals:
            last_auto_signal_ok = True
            return

        for sig in signals:
            text = build_signal_text(sig)

            # ارسال برای ADMIN
            if ADMIN_ID:
                try:
                    await context.bot.send_message(chat_id=ADMIN_ID, text=text)
                except Exception as e:
                    logger.error(f"send to ADMIN error: {e}")

            # ارسال برای VIPها
            for cid in list(VIP_IDS):
                try:
                    await context.bot.send_message(chat_id=cid, text=text)
                except Exception as e:
                    logger.error(f"send to VIP {cid} error: {e}")

            daily_stats["signals"] += 1
            daily_stats["pa_breakouts"] += 1

        last_auto_signal_ok = True
    except Exception as e:
        logger.error(f"auto_signal error: {e}")
        last_auto_signal_ok = False

# =========================================
# APP & MAIN
# =========================================

def build_app():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not set")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("summary", summary_cmd))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CommandHandler("test_d1", test_d1_cmd))

    app.add_handler(CommandHandler("addvip", add_vip))
    app.add_handler(CommandHandler("rmvip", rm_vip))
    app.add_handler(CommandHandler("viplist", vip_list_cmd))

    # auto_signal هر ۳ دقیقه
    app.job_queue.run_repeating(auto_signal_job, interval=180, first=20)

    return app

async def main():
    app = build_app()

    if WEBHOOK_URL:
        full_url = WEBHOOK_URL.rstrip("/") + WEBHOOK_PATH
        await app.initialize()
        await app.start()
        await app.bot.set_webhook(url=full_url)
        logger.info(f"Webhook set: {full_url}")
        await app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH.lstrip("/"),
        )
    else:
        # Polling mode
        await app.initialize()
        await app.start()
        logger.info("Running in polling mode")
        await app.updater.start_polling()
        await app.updater.idle()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
