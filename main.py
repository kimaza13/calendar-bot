import os
from flask import Flask, request, jsonify
from config import TELEGRAM_BOT_TOKEN, WEBHOOK_URL
from bot import api as tg
from bot.handlers import handle_update
from services.reminders import init_db
from services.scheduler import start_scheduler
import threading
import time

app = Flask(__name__)


@app.route(f"/webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    try:
        handle_update(request.json)
    except Exception as e:
        print(f"Update error: {e}")
    return jsonify({"ok": True})


@app.route("/health")
def health():
    return "ok"

def _keep_alive():
    import requests
    while True:
        time.sleep(600)  # каждые 10 минут
        try:
            requests.get(f"{WEBHOOK_URL}/health", timeout=10)
        except Exception:
            pass

if __name__ == "__main__":
    init_db()
    start_scheduler()
    threading.Thread(target=_keep_alive, daemon=True, name="keep-alive").start()
    tg.set_webhook(f"{WEBHOOK_URL}/webhook/{TELEGRAM_BOT_TOKEN}")
    print("Webhook установлен. Бот запущен.")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)