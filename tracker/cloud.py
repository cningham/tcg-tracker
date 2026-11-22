"""Cloud mode: run from GitHub Actions, no database, no web page.

The watchlist comes from watchlist.txt (or a WATCHLIST secret, which wins
if set and keeps the list private). One card per line:

    Charizard ex 199 | 50 | must: 199/165 | not: japanese, jumbo
    Pikachu 025 151  | 12.50
    Johnny Silverhand | 8 | bin-only

    search words | max £ incl. postage | options...

Options: "must: a, b" (title must contain all), "not: x, y" (title must not
contain any), "bin-only" (skip auctions). Lines starting with # are ignored.

Listings already alerted are remembered in seen.json, which the workflow keeps
in the Actions cache between runs.

Logs in a public repo are public, so this prints only counts, never card names,
prices or listing titles.
"""
import argparse
import json
import logging
import os
import time
from pathlib import Path

from . import checker, config, notify
from .ebay import Ebay

log = logging.getLogger("tracker")


def parse_watchlist(text):
    cards, errors = [], []
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            errors.append(f"line {n}: needs 'search words | max price'")
            continue
        try:
            max_price = float(parts[1].replace("£", "").replace(",", ""))
        except ValueError:
            errors.append(f"line {n}: max price isn't a number")
            continue
        card = {"name": parts[0], "query": parts[0], "max_price": max_price,
                "must_include": "", "exclude": "", "include_auctions": True}
        for opt in parts[2:]:
            key, _, val = opt.partition(":")
            key = key.strip().lower()
            if key in ("must", "must have"):
                card["must_include"] = val.strip()
            elif key in ("not", "exclude", "must not"):
                card["exclude"] = val.strip()
            elif key in ("bin-only", "bin only", "no auctions"):
                card["include_auctions"] = False
            elif opt:
                errors.append(f"line {n}: unknown option")
        card["key"] = f"{card['query'].lower()}|{max_price:.2f}"
        cards.append(card)
    return cards, errors


def load_seen(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def save_seen(path, seen):
    # Keep it from growing forever: drop entries older than 30 days.
    cutoff = time.time() - 30 * 86400
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    Path(path).write_text(json.dumps(seen))


def check_all(ebay, cards, seen):
    """One pass over all cards. Returns (alerts sent, errors)."""
    alerts = errors = 0
    for card in cards:
        kinds = [("FIXED_PRICE", None)]
        if card["include_auctions"]:
            kinds.append(("AUCTION", config.AUCTION_WINDOW_MINUTES))
        for kind, window in kinds:
            try:
                results = ebay.search(card["query"], card["max_price"], kind=kind,
                                      ending_within_minutes=window)
            except Exception as e:
                errors += 1
                log.warning("search failed: %s", type(e).__name__)
                continue
            for m in results:
                key = f"{card['key']}|{m['item_id']}"
                if key in seen or checker.reject_reason(card, m):
                    continue
                subject, body = notify.format_alert(card, m)
                notify.send(subject, body)
                seen[key] = time.time()
                alerts += 1
    return alerts, errors


def load_watchlist_text(path="watchlist.txt"):
    """The WATCHLIST secret wins if set; otherwise watchlist.txt in the repo."""
    text = os.environ.get("WATCHLIST", "").strip()
    if text:
        return text
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def hello(cards, problems):
    """Confirm the setup works: test eBay, then send a Telegram/email summary."""
    lines = ["TCG Tracker check-in."]
    ok = True
    try:
        Ebay()._get_token()
        lines.append("eBay connection: OK")
    except Exception as e:
        ok = False
        lines.append(f"eBay connection: FAILED ({e})"[:300])
    if cards:
        lines.append(f"Watching {len(cards)} card(s):")
        for c in cards:
            extra = "" if c["include_auctions"] else " (Buy It Now only)"
            lines.append(f"- {c['query']}: up to £{c['max_price']:.2f}{extra}")
    else:
        lines.append("No cards in the watchlist yet.")
    for prob in problems:
        lines.append(f"Watchlist problem, {prob}")
    res = notify.send("Tracker is set up", "\n".join(lines))
    for ch, err in res:
        log.info("%s: %s", ch, "sent" if err is None else f"FAILED: {err[:200]}")
    if not res:
        log.error("No alert channel: add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID secrets.")
    log.info("eBay connection: %s", "OK" if ok else "FAILED (check EBAY_CLIENT_ID / EBAY_CLIENT_SECRET)")
    if not ok or not res or any(err for _, err in res):
        raise SystemExit(1)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=0,
                   help="keep checking for this many minutes (0 = check once)")
    p.add_argument("--every", type=float, default=config.CHECK_EVERY_MINUTES,
                   help="minutes between checks")
    p.add_argument("--seen", default="state/seen.json")
    p.add_argument("--watchlist", default="watchlist.txt")
    p.add_argument("--hello", action="store_true",
                   help="send a setup confirmation, then check once")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    # Keep third-party libraries from logging URLs (which can contain tokens).
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    cards, problems = parse_watchlist(load_watchlist_text(args.watchlist))
    for prob in problems:
        log.warning("watchlist %s", prob)
    if args.hello:
        hello(cards, problems)
    if not cards:
        log.info("Watchlist is empty, nothing to check.")
        return
    if not notify.channels():
        log.warning("No alert channel configured (Telegram or email secrets).")

    Path(args.seen).parent.mkdir(parents=True, exist_ok=True)
    seen = load_seen(args.seen)
    ebay = Ebay()
    deadline = time.time() + args.minutes * 60
    passes = 0
    while True:
        started = time.time()
        alerts, errors = check_all(ebay, cards, seen)
        save_seen(args.seen, seen)
        passes += 1
        log.info("pass %d: %d card(s), %d alert(s), %d error(s)", passes, len(cards), alerts, errors)
        next_at = started + args.every * 60
        if next_at >= deadline:
            break
        time.sleep(max(0, next_at - time.time()))


if __name__ == "__main__":
    main()
