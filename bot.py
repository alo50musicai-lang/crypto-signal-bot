import os
import threading
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from http.server import HTTPServer, BaseHTTPRequestHandler

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", 10000))

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), SimpleHandler)
    server.serve_forever()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ربات سیگنال آماده است ✅")

def run_bot():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_server).start()
    run_bot()