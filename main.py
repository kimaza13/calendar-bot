import os
from flask import Flask, request, jsonify
from config import TELEGRAM_BOT_TOKEN, WEBHOOK_URL
from bot import api as tg
from bot.handlers import handle_update

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


if __name__ == "__main__":
    tg.set_webhook(f"{WEBHOOK_URL}/webhook/{TELEGRAM_BOT_TOKEN}")
    print("Webhook установлен. Бот запущен.")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
