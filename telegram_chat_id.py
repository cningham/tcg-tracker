"""Prints your Telegram chat id. Message your bot first, then run: python telegram_chat_id.py"""
import requests

from tracker import config

if not config.TELEGRAM_BOT_TOKEN:
    raise SystemExit("Put TELEGRAM_BOT_TOKEN in .env first.")
r = requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates", timeout=20).json()
chats = {u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "")
         for u in r.get("result", []) if "message" in u}
if not chats:
    print("No messages found. Send your bot any message in Telegram, then run this again.")
for cid, name in chats.items():
    print(f"TELEGRAM_CHAT_ID={cid}   ({name})")
