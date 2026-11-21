"""Cloud mode: run from GitHub Actions, no database, no web page.

The watchlist comes from the WATCHLIST environment variable (a GitHub Actions
repository variable, so it is not public). One card per line:

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


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=0,
                   help="keep checking for this many minutes (0 = check once)")
    p.add_argument("--every", type=float, default=config.CHECK_EVERY_MINUTES,
                   help="minutes between checks")
    p.add_argument("--seen", default="state/seen.json")
    p.add_argument("--test-alert", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    # Keep third-party libraries from logging URLs (which can contain tokens).
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if args.test_alert:
        res = notify.send("Test alert", "TCG Tracker test alert from GitHub Actions. Alerts work.")
        for ch, err in res:
            log.info("%s: %s", ch, "sent" if err is None else "FAILED")
        if not res or any(err for _, err in res):
            raise SystemExit(1)
        return

    import os
    cards, problems = parse_watchlist(os.environ.get("WATCHLIST", ""))
    for prob in problems:
        log.warning("watchlist %s", prob)
    if not cards:
        raise SystemExit("WATCHLIST is empty. Add it under Settings > Secrets and variables > Actions > Variables.")
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
