"""Alert delivery: Telegram and/or email. Each is used only if configured in .env."""
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import requests

from . import config

log = logging.getLogger(__name__)


def channels():
    out = []
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        out.append("telegram")
    if config.SMTP_USER and config.SMTP_PASSWORD and config.EMAIL_TO:
        out.append("email")
    return out


def _time_left(ends_at):
    if not ends_at:
        return ""
    try:
        end = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    mins = int((end - datetime.now(timezone.utc)).total_seconds() // 60)
    return f"{max(mins, 0)} min left"


def format_alert(card, m):
    sym = "£" if m["currency"] == "GBP" else m["currency"] + " "
    postage = ("postage unknown" if m["postage"] is None
               else "free postage" if m["postage"] == 0
               else f"incl. {sym}{m['postage']:.2f} postage")
    if m["kind"] == "AUCTION":
        bids = m.get("bids")
        what = f"Auction, {_time_left(m.get('ends_at'))}" + (f", {bids} bids" if bids is not None else "")
    else:
        what = "Buy It Now"
    subject = f"{card['name']}: {sym}{m['total']:.2f} (max {sym}{card['max_price']:.2f})"
    body = (f"{subject}\n{what}, {postage}\n{m['title']}\n{m['url']}")
    return subject, body


def send_telegram(text):
    r = requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": False},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text[:200]}")


def send_email(subject, body):
    msg = EmailMessage()
    msg["Subject"] = f"[TCG Tracker] {subject}"
    msg["From"] = config.SMTP_USER
    msg["To"] = config.EMAIL_TO
    msg.set_content(body)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as s:
        s.starttls()
        s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        s.send_message(msg)


def send(subject, body):
    """Send to every configured channel. Returns list of (channel, error or None)."""
    results = []
    for ch in channels():
        try:
            if ch == "telegram":
                send_telegram(body)
            else:
                send_email(subject, body)
            results.append((ch, None))
        except Exception as e:  # keep going if one channel fails
            log.warning("Alert via %s failed: %s", ch, e)
            results.append((ch, str(e)))
    if not results:
        log.warning("No alert channel configured; alert only shown in the app: %s", subject)
    return results
