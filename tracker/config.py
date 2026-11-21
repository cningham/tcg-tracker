"""Settings, read from the .env file next to run.py."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(name, default=""):
    return os.environ.get(name, default).strip()


def _int(name, default):
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


# eBay developer keys (https://developer.ebay.com/my/keys, "Production" keyset)
EBAY_CLIENT_ID = _get("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = _get("EBAY_CLIENT_SECRET")
EBAY_MARKETPLACE = _get("EBAY_MARKETPLACE", "EBAY_GB")
EBAY_CURRENCY = _get("EBAY_CURRENCY", "GBP")
EBAY_DELIVERY_COUNTRY = _get("EBAY_DELIVERY_COUNTRY", "GB")
# 183454 = "CCG Individual Cards". Leave blank to search all categories.
EBAY_CATEGORY_ID = _get("EBAY_CATEGORY_ID", "183454")
# Only items listed in these countries (comma separated, blank = anywhere).
EBAY_ITEM_LOCATION = _get("EBAY_ITEM_LOCATION", "")

# How often to check eBay, in minutes.
CHECK_EVERY_MINUTES = max(1, _int("CHECK_EVERY_MINUTES", 5))
# Alert on an auction only when it has this many minutes or fewer left.
AUCTION_WINDOW_MINUTES = _int("AUCTION_WINDOW_MINUTES", 10)

# Words that mark a listing as graded / not a real raw card. Checked against titles.
DEFAULT_EXCLUDE = _get(
    "EXCLUDE_WORDS",
    "psa,cgc,bgs,sgc,ace grading,graded,slab,slabbed,tag grading,beckett,"
    "proxy,custom,orica,replica,fake,digital,code card,empty,lot of,bundle,choose,pick your",
)

# Telegram (optional)
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

# Email (optional)
SMTP_HOST = _get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USER = _get("SMTP_USER")
SMTP_PASSWORD = _get("SMTP_PASSWORD")
EMAIL_TO = _get("EMAIL_TO")

WEB_PORT = _int("WEB_PORT", 5055)
DB_PATH = Path(_get("DB_PATH", str(ROOT / "tracker.db")))
