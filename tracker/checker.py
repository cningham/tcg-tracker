"""Checks every watched card against eBay and sends alerts for new matches."""
import logging
import threading

from . import config, db, notify
from .ebay import Ebay

log = logging.getLogger(__name__)
_lock = threading.Lock()


def _words(text):
    return [w.strip().lower() for w in (text or "").split(",") if w.strip()]


def reject_reason(card, m):
    """Why a listing doesn't count, or None if it's a real match."""
    title = m["title"].lower()
    if m["condition_id"] == "2750" or "graded" == m["condition"].lower():
        return "graded"
    for w in _words(config.DEFAULT_EXCLUDE) + _words(card.get("exclude")):
        if w in title:
            return f"title has '{w}'"
    for w in _words(card.get("must_include")):
        if w not in title:
            return f"title missing '{w}'"
    if m["total"] > card["max_price"]:
        return "over max with postage"
    return None


def calls_per_day(cards):
    per_cycle = sum(2 if c["include_auctions"] else 1 for c in cards if c["enabled"])
    return per_cycle * (24 * 60 // config.CHECK_EVERY_MINUTES)


def check_card(ebay, card):
    """Return a list of new matches for this card (already saved and alerted)."""
    kinds = [("FIXED_PRICE", None)]
    if card["include_auctions"]:
        kinds.append(("AUCTION", config.AUCTION_WINDOW_MINUTES))
    new = []
    for kind, window in kinds:
        for m in ebay.search(card["query"], card["max_price"], kind=kind,
                             ending_within_minutes=window):
            if reject_reason(card, m):
                continue
            if db.record_match(card["id"], m):
                subject, body = notify.format_alert(card, m)
                notify.send(subject, body)
                new.append(m)
    return new


def run_once(ebay=None, card_ids=None):
    """Check all enabled cards (or just card_ids). Safe to call from several threads."""
    if not _lock.acquire(blocking=False):
        log.info("A check is already running; skipping.")
        return 0
    try:
        ebay = ebay or Ebay()
        cards = db.list_cards(enabled_only=True)
        if card_ids:
            cards = [c for c in cards if c["id"] in card_ids]
        total = 0
        for card in cards:
            try:
                found = check_card(ebay, card)
                total += len(found)
                db.mark_checked(card["id"])
                if found:
                    log.info("%s: %d new match(es)", card["name"], len(found))
            except Exception as e:
                log.warning("%s: %s", card["name"], e)
                db.mark_checked(card["id"], error=str(e))
        return total
    finally:
        _lock.release()


def loop(stop_event):
    ebay = Ebay()
    while not stop_event.is_set():
        run_once(ebay)
        stop_event.wait(config.CHECK_EVERY_MINUTES * 60)
