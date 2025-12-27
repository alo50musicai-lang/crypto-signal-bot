import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ایمپورت فایل‌هایی که خودت ساختی
from data import get_klines
from price_action import detect_structure


# ======================
# تنظیمات
# ======================
TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", 10000))


# ======================
# Fake Web Server (برای Render)
# ======================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), SimpleHandler)
    server.serve_forever()


# ======================
# Telegram Command
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = "BTCUSDT"
    timeframe = "5m"

    candles = get_klines(symbol, timeframe)
    structure = detect_structure(candles)

    await update.message.reply_text(
        f"""
📊 {symbol}
🕒 TF: {timeframe}
📈 Market Structure: {structure}

⚠️ فقط تحلیل – تصمیم با خودته
"""
    )


# ======================
# Main
# ======================
def run_bot():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()


if __name__ == "__main__":
    threading.Thread(target=run_server).start()
    run_bot()