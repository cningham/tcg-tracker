"""Telegram commands for managing the watchlist from your phone.

    /add Charizard ex 199/165 50    watch a card, max £50 incl. postage
    /list                           show what's being watched
    /remove 2                       stop watching card 2
    /price 2 45                     change card 2's max to £45
    /help

Only messages from TELEGRAM_CHAT_ID are obeyed. Changes are saved to
watchlist.txt and committed to the repo, so they stick between runs.
"""
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

import requests

from . import config

log = logging.getLogger("tracker")

HELP = (
    "Easiest: share a card from Collectr to me, then reply with your max price.\n\n"
    "Commands:\n"
    "/add Charizard ex 199/165 50  (watch a card, max £50 incl. postage)\n"
    "/list  (show your cards)\n"
    "/market 2  (10 cheapest eBay listings for card 2, any price; or /market + a name or Collectr link)\n"
    "/remove 2  (stop watching card 2)\n"
    "/price 2 45  (change card 2's max to £45)\n"
    "/condition 2 NM  (card 2: Near Mint only. Also EX, VG or any)\n"
    "Use 'all' instead of a number to change every card, e.g. /condition all EX\n\n"
    "Add 'bin' at the end of /add to skip auctions, and NM/EX/VG for a minimum condition, "
    "e.g. /add Pikachu 025/165 12 bin NM"
)

NUMBER = re.compile(r"^#?(\w*\d+)/(\w*\d+)$")   # 199/165, TG12/TG30, #025/198


def enabled():
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _api(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}",
                      json=params, timeout=params.get("timeout", 0) + 15)
    r.raise_for_status()
    return r.json().get("result")


def register_commands():
    """Shows the commands in Telegram's "/" menu."""
    _api("setMyCommands", commands=[
        {"command": "add", "description": "Watch a card: /add Charizard ex 199/165 50"},
        {"command": "list", "description": "Show your cards"},
        {"command": "market", "description": "Cheapest listings now: /market 2 or /market Scyther 003/106"},
        {"command": "remove", "description": "Stop watching a card: /remove 2"},
        {"command": "price", "description": "Change a max price: /price 2 45"},
        {"command": "condition", "description": "Minimum condition: /condition 2 NM (or EX, VG, any)"},
        {"command": "help", "description": "How to use me"},
    ])


def reply(text, html=False):
    params = dict(chat_id=config.TELEGRAM_CHAT_ID, text=text, disable_web_page_preview=True)
    if html:
        params["parse_mode"] = "HTML"
    _api("sendMessage", **params)


# -- watchlist file -------------------------------------------------------

def read_lines(path):
    try:
        return Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def card_lines(lines):
    """Indexes of lines that are cards (not comments/blank)."""
    return [i for i, l in enumerate(lines) if l.strip() and not l.strip().startswith("#")]


def line_for_add(text):
    """'/add Charizard ex 199/165 50 bin' -> 'Charizard ex 199 | 50 | must: 199/165 | bin-only'"""
    from .condition import SHORT, parse_level
    words = text.split()
    bin_only = False
    min_cond = None
    while words:
        last = words[-1].lower()
        if last in ("bin", "bin-only", "buyitnow"):
            bin_only = True
        elif last in ("nm", "ex", "lp", "vg", "mp", "poor") and len(words) > 2:
            min_cond = parse_level(last)
        else:
            break
        words = words[:-1]
    if len(words) < 2:
        return None, "Tell me the card and a max price, e.g. /add Charizard ex 199/165 50"
    try:
        price = float(words[-1].replace("£", "").replace(",", ""))
    except ValueError:
        return None, "The last thing should be your max price, e.g. /add Charizard ex 199/165 50"
    words = words[:-1]
    if "|" in " ".join(words):
        return None, "Please don't use | in /add."
    must = ""
    query_words = []
    for w in words:
        m = NUMBER.match(w)
        if m:
            # Search for the number alone (titles write it many ways),
            # but require the full 199/165 in the title to avoid other cards.
            must = f"{m.group(1)}/{m.group(2)}"
            query_words.append(m.group(1))
        else:
            query_words.append(w)
    parts = [search_words(" ".join(query_words)), f"{price:g}"]
    if must:
        parts.append(f"must: {must}")
    if bin_only:
        parts.append("bin-only")
    if min_cond:
        parts.append(f"min: {SHORT[min_cond]}")
    return " | ".join(parts), None


URL = re.compile(r"https?://\S+")
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def search_words(query):
    """Turn a card name into eBay search words: drop (brackets), dashes and
    words sellers rarely use, so the search isn't too strict."""
    q = re.sub(r"[\(\[].*?[\)\]]", " ", query)
    q = re.sub(r"(^|\s)[-–—:]+(?=\s|$)", " ", q)
    words = [w for w in q.split() if w.lower() not in ("retail", "collectr")]
    return " ".join(words) or query


def _meta(html, *names):
    for n in names:
        m = (re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']+)' % re.escape(n), html, re.I)
             or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']%s["\']' % re.escape(n), html, re.I))
        if m:
            return m.group(1)
    return ""


def _clean_title(t):
    import html as htmlmod
    t = htmlmod.unescape(t or "").strip()
    for sep in (" | ", " - Collectr", " – Collectr", " · "):
        if sep in t:
            t = t.split(sep)[0].strip()
    t = re.sub(r"\bon Collectr\b.*$", "", t, flags=re.I).strip()
    if t.lower() in ("", "collectr", "collectr app", "collectr - tcg collector app"):
        return ""
    return t


_SYM = {"GBP": "£", "USD": "$", "EUR": "€"}


def _page_price(page):
    """Market price shown on a shared page, as text like '£12.34', or ''."""
    amt = _meta(page, "product:price:amount", "og:price:amount")
    if amt:
        cur = _meta(page, "product:price:currency", "og:price:currency").upper()
        return f"{_SYM.get(cur, cur + ' ' if cur else '')}{amt}"
    m = re.search(r'"(?:marketPrice|market_price|currentPrice|price)"\s*:\s*"?(\d+(?:\.\d+)?)', page)
    if m:
        cur = re.search(r'"(?:priceCurrency|currency)"\s*:\s*"([A-Z]{3})"', page)
        return f"{_SYM.get(cur.group(1), cur.group(1) + ' ') if cur else ''}{float(m.group(1)):.2f}"
    desc = _meta(page, "og:description", "description", "twitter:description")
    m = re.search(r"([£$€])\s?(\d[\d,]*(?:\.\d{1,2})?)", desc)
    return f"{m.group(1)}{m.group(2)}" if m else ""


def read_link(url):
    """(card name, price text) for a shared link, e.g. from Collectr."""
    final_url, name, price = url, "", ""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
        final_url = r.url
        page = r.text[:400000]
        price = _page_price(page)
        log.info("link fetch: status %s, %d bytes, price %s, description: %s", r.status_code, len(page),
                 "found" if price else "not found",
                 _meta(page, "og:description", "description")[:160])
        for cand in (_meta(page, "og:title", "twitter:title"),
                     *re.findall(r'"@type"\s*:\s*"Product".{0,400}?"name"\s*:\s*"([^"]+)"', page, re.S)[:1],
                     *(re.findall(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)[:1])):
            name = _clean_title(cand)
            if name:
                return name, price
    except Exception as e:
        log.info("link fetch failed: %s", type(e).__name__)
    # Fall back to the words in the link itself, e.g. /product/charizard-ex-199-165
    from urllib.parse import unquote, urlparse
    for seg in reversed([x for x in urlparse(final_url).path.split("/") if x]):
        seg = unquote(seg)
        if re.search(r"[a-zA-Z]{3,}", seg) and not re.fullmatch(r"[0-9a-f-]{20,}", seg):
            if seg.lower() in ("product", "products", "explore", "card", "cards", "item", "portfolio"):
                continue
            return re.sub(r"[-_]+", " ", seg).strip(), price
    return "", price


def name_from_link(url):
    return read_link(url)[0]


def _price_from(text):
    m = re.fullmatch(r"£?\s*(\d+(?:[.,]\d{1,2})?)\s*(?:£|gbp)?", text.strip(), re.I)
    return float(m.group(1).replace(",", ".")) if m else None


def describe(line):
    parts = [p.strip() for p in line.split("|")]
    text = f"{parts[0]}: up to £{float(parts[1]):.2f}" if len(parts) > 1 else line
    extras = [p.replace("min:", "min condition:") for p in parts[2:]
              if p and not p.lower().startswith("collectr:")]
    return text + (f" ({', '.join(extras)})" if extras else "")


def handle(text, lines, state=None):
    """Apply one command to a copy of the watchlist lines.
    Returns (reply text, new lines or None if nothing changed).
    `state` holds a card waiting for its max price after a shared link."""
    state = {} if state is None else state
    text = (text or "").strip()

    link = URL.search(text)
    if link:
        url = link.group(0).rstrip(").,")
        rest = URL.sub(" ", text).strip()
        price = _price_from(rest.split()[-1]) if rest.split() else None
        if price is not None:
            rest = " ".join(rest.split()[:-1])
        name, page_price = read_link(url)
        name = name or re.sub(r"(?i)check out|on collectr|collectr|!", " ", rest).strip()
        if not name:
            return ("I couldn't read the card name from that link. Send it like "
                    "/add Charizard ex 199/165 50 instead."), None
        shown = f" (Collectr price {page_price})" if page_price else ""
        # Already watching this card? Attach the link (and new price) to it.
        new_line, _ = line_for_add(f"{name} 1")
        lines = list(lines)
        for n, i in enumerate(card_lines(lines), 1):
            parts = [p.strip() for p in lines[i].split("|")]
            if new_line and parts[0].lower() == new_line.split("|")[0].strip().lower():
                parts = [p for p in parts if not p.lower().startswith("collectr:")] + [f"collectr: {url}"]
                if price is not None:
                    parts[1] = f"{price:g}"
                lines[i] = " | ".join(parts)
                return f"Card {n} is already on your list, I've linked it to Collectr{shown}: {describe(lines[i])}", lines
        if price is None:
            state["pending"] = {"name": name, "url": url}
            return (f"Found: {name}{shown}\nWhat's the most you'd pay, postage included? "
                    "Reply with just the number, e.g. 25"), None
        state["pending"] = {"name": name, "url": url}
        text = f"/add {name} {price:g}"
    elif state.get("pending") and _price_from(text) is not None:
        p = state["pending"]
        p = p if isinstance(p, dict) else {"name": p, "url": ""}
        state["pending"] = p
        text = f"/add {p['name']} {_price_from(text):g}"

    cmd, _, rest = text.partition(" ")
    cmd = cmd.lower().split("@")[0]
    lines = list(lines)
    idx = card_lines(lines)

    if cmd == "/add":
        pending = state.pop("pending", None)
        line, err = line_for_add(rest)
        if err:
            return err, None
        if isinstance(pending, dict) and pending.get("url") and rest.startswith(pending["name"]):
            line += f" | collectr: {pending['url']}"
        lines.append(line)
        return f"Added card {len(idx) + 1}: {describe(line)}\nI'll message you when one is listed under that price.", lines

    if cmd == "/list":
        if not idx:
            return "You're not watching any cards yet.\n\n" + HELP, None
        out = [f"{n}. {describe(lines[i])}" for n, i in enumerate(idx, 1)]
        if os.environ.get("WATCHLIST", "").strip():
            out.append("\nNote: a WATCHLIST secret is set on GitHub, and it overrides this list.")
        return "\n".join(out), None

    def targets(arg):
        """'2' -> [line index of card 2]; 'all' -> every card. None if invalid."""
        arg = arg.strip().lower()
        if arg in ("all", "*", "everything"):
            return list(idx) or None
        try:
            n = int(arg)
            return [idx[n - 1]] if n >= 1 else None
        except (ValueError, IndexError):
            return None

    def numbered(changed):
        return "\n".join(f"{idx.index(i) + 1}. {describe(lines[i])}" for i in changed)

    if cmd in ("/remove", "/delete"):
        which = targets(rest)
        if not which:
            return "Which card? Send /list to see the numbers, then e.g. /remove 2 (or /remove all)", None
        removed = [describe(lines[i]) for i in which]
        for i in sorted(which, reverse=True):
            lines.pop(i)
        if len(removed) == 1:
            return f"Stopped watching: {removed[0]}", lines
        return f"Stopped watching all {len(removed)} cards.", lines

    if cmd == "/price":
        try:
            n_s, p_s = rest.split()
            price = float(p_s.replace("£", ""))
        except ValueError:
            n_s = None
        which = targets(n_s) if n_s else None
        if not which:
            return "Send it like /price 2 45 (card 2, new max £45), or /price all 45. /list shows the numbers.", None
        for i in which:
            parts = [p.strip() for p in lines[i].split("|")]
            parts[1] = f"{price:g}"
            lines[i] = " | ".join(parts)
        return "Updated:\n" + numbered(which), lines

    if cmd in ("/condition", "/min", "/cond"):
        from .condition import SHORT, parse_level
        args = rest.split(None, 1)
        which = targets(args[0]) if args else None
        lvl = parse_level(args[1]) if len(args) > 1 else None
        if not which or lvl is None:
            return ("Send it like /condition 2 NM (card 2, Near Mint only), or /condition all EX for every card.\n"
                    "Options: NM, EX (excellent/lightly played), VG (very good/played), any."), None
        for i in which:
            parts = [p.strip() for p in lines[i].split("|") if not p.strip().lower().startswith("min:")]
            if lvl:
                parts.append(f"min: {SHORT[lvl]}")
            lines[i] = " | ".join(parts)
        what = f"only {SHORT[lvl]} or better" if lvl else "any condition"
        who = "All cards now alert" if len(which) > 1 else f"Card {idx.index(which[0]) + 1} now alerts"
        return f"{who} for {what}:\n" + numbered(which), lines

    return HELP, None


def save(path, lines_text, message):
    Path(path).write_text(lines_text, encoding="utf-8")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    # Commit so the change sticks for the next run. Pushes made with the
    # workflow's own token don't start another workflow run.
    git = lambda *a: subprocess.run(["git", *a], check=True, capture_output=True, text=True)
    try:
        git("config", "user.name", "github-actions[bot]")
        git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
        git("add", path)
        git("commit", "-m", message)
        for _ in range(3):
            try:
                git("pull", "--rebase", "-q", "origin", "main")
                git("push", "-q", "origin", "HEAD:main")
                return
            except subprocess.CalledProcessError:
                continue
        log.warning("Couldn't push watchlist change")
    except subprocess.CalledProcessError as e:
        log.warning("Couldn't commit watchlist change: %s", (e.stderr or "")[:200])


def preview(ebay, line):
    """What's on eBay right now for a newly added card (Buy It Now, any price)."""
    from . import checker
    from .cloud import parse_watchlist
    cards, _ = parse_watchlist(line)
    if not cards or ebay is None:
        return ""
    card = dict(cards[0], max_price=10**6)
    try:
        items = ebay.search(search_words(card["query"]), 10**6, kind="FIXED_PRICE", limit=50)
    except Exception:
        return ""
    ok = [m for m in items if not checker.reject_reason(card, m)]
    if not ok:
        return ("\nRight now eBay has no Buy It Now listings for that search. If that seems wrong, "
                "the name may be too specific: /remove it and /add a shorter name.")
    cheapest = min(m["total"] for m in ok)
    more = "+" if len(items) >= 50 else ""
    return f"\nRight now on eBay: {len(ok)}{more} Buy It Now listing(s), cheapest £{cheapest:.2f} with postage."


def _left(ends_at):
    from datetime import datetime, timezone
    try:
        end = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return ""
    mins = max(0, int((end - datetime.now(timezone.utc)).total_seconds() // 60))
    if mins >= 1440:
        return f"{mins // 1440}d {mins % 1440 // 60}h left"
    if mins >= 60:
        return f"{mins // 60}h {mins % 60}m left"
    return f"{mins}m left"


def market(ebay, arg, lines):
    """/market: the cheapest current listings for a card, at any price."""
    from . import checker
    from .cloud import parse_watchlist
    arg = (arg or "").strip()
    if not arg:
        return ("Which card? Send /market 2 for card 2 on your /list, "
                "or /market Charizard ex 199/165, or share a Collectr link after /market.")
    idx = card_lines(lines)
    top = ""  # price line shown above the list
    if arg.isdigit() and 1 <= int(arg) <= len(idx):
        line = lines[idx[int(arg) - 1]]
        watched, _ = parse_watchlist(line)
        link_price = read_link(watched[0]["collectr"])[1] if watched and watched[0].get("collectr") else ""
        top = (f"Collectr price: {link_price}" if link_price
               else f"Your max price: £{watched[0]['max_price']:.2f}" if watched else "")
    else:
        link = URL.search(arg)
        name, link_price = read_link(link.group(0)) if link else (arg, "")
        if link_price:
            top = f"Collectr price: {link_price}"
        if not name:
            return "I couldn't read the card name from that link. Try /market followed by the card name."
        line, err = line_for_add(f"{name} 1")
        if err:
            return err
    cards, _ = parse_watchlist(line)
    card = dict(cards[0], max_price=10**6)
    query = search_words(card["query"])
    found = []
    for kind in ("FIXED_PRICE", "AUCTION"):
        try:
            found += ebay.search(query, 10**6, kind=kind, limit=100, sort="price")
        except Exception as e:
            log.warning("market search failed: %s", type(e).__name__)
            return "Sorry, eBay didn't answer. Try again in a minute."
    found = [m for m in found if not checker.reject_reason(card, m)]
    from .condition import SHORT, ConditionChecker
    conds = ConditionChecker(ebay)
    min_cond = card.get("min_condition") or 0
    seen, unique, shown = set(), [], []
    for m in sorted(found, key=lambda m: m["total"]):
        if m["item_id"] not in seen:
            seen.add(m["item_id"])
            unique.append(m)
    # Look up condition for the cheapest ones until there are 10 to show.
    skipped = 0
    for m in unique:
        if len(shown) >= 10:
            break
        lvl, source = conds.level(m)
        if min_cond and lvl and lvl < min_cond:
            skipped += 1
            continue
        m["cond_short"] = (SHORT[lvl] + ("?" if source == "title" else "")) if lvl else "cond. ?"
        shown.append(m)
    total = len(unique) - skipped if len(shown) < 10 else None
    if not shown:
        unique = []
    from html import escape
    if not unique:
        return escape((f"{top}\n\n" if top else "") + f"No raw listings on eBay for \"{query}\" right now.\n"
                      "If that seems wrong, try a shorter name, e.g. /market Scyther 003/106")
    cond_note = f", {SHORT[min_cond]} or better" if min_cond else ""
    head = (f"eBay now for \"{query}\"{cond_note}: "
            + (f"{total} listing(s):" if total is not None else "10 cheapest:"))
    if top:
        head = f"{top}\n\n{head}"
    rows = []
    for n, m in enumerate(shown, 1):
        post = "" if m["postage"] is None else (" free post" if m["postage"] == 0 else f" incl. £{m['postage']:.2f} post")
        if m["kind"] == "AUCTION":
            bids = f", {m['bids']} bids" if m.get("bids") is not None else ""
            what = f"auction, {_left(m.get('ends_at'))}{bids}"
        else:
            what = "Buy It Now"
        title = m["title"] if len(m["title"]) <= 70 else m["title"][:67] + "..."
        link = (f'<a href="{escape(m["url"], quote=True)}">{escape(title)}</a>'
                if m.get("url", "").startswith("https://") else escape(title))
        rows.append(f"{n}. £{m['total']:.2f}{escape(post)} · {escape(what)} · {escape(m['cond_short'])}\n    {link}")
    note = ("\n\nTotals include postage to the UK. Graded slabs are left out. Tap a title to open it on eBay.\n"
            "Condition: NM near mint, EX excellent, VG very good. ? = guessed from the title or not stated.")
    return escape(head) + "\n" + "\n".join(rows) + note


class Bot:
    def __init__(self, path="watchlist.txt", ebay=None, state_path="state/bot.json"):
        self.path = path
        self.offset = None
        self.ebay = ebay
        self.state_path = state_path
        try:
            self.state = json.loads(Path(state_path).read_text())
        except (OSError, ValueError):
            self.state = {}

    def poll(self, wait_seconds):
        """Wait up to wait_seconds for commands and apply them.
        Returns True if the watchlist changed."""
        if not enabled():
            return False
        params = {"timeout": int(max(0, min(wait_seconds, 50))), "allowed_updates": ["message"]}
        if self.offset is not None:
            params["offset"] = self.offset
        try:
            updates = _api("getUpdates", **params) or []
        except Exception as e:
            log.warning("Telegram poll failed: %s", type(e).__name__)
            time.sleep(min(10, max(0, wait_seconds)))
            return False
        changed = False
        for u in updates:
            self.offset = u["update_id"] + 1
            msg = u.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
                continue  # ignore anyone who isn't you
            text = msg.get("text", "")
            try:
                before = read_lines(self.path)
                cmd, _, arg = text.strip().partition(" ")
                if cmd.lower().split("@")[0] in ("/market", "/m", "/prices"):
                    self.state.pop("pending", None)
                    reply(market(self.ebay, arg, before) if self.ebay else "eBay isn't connected.", html=True)
                    continue
                answer, new_lines = handle(text, before, self.state)
                self._save_state()
                if new_lines is not None:
                    save(self.path, "\n".join(new_lines) + "\n", "Watchlist: changed via Telegram")
                    changed = True
                    if len(new_lines) > len(before):  # a card was added
                        answer += preview(self.ebay, new_lines[-1])
                reply(answer)
            except Exception as e:
                log.warning("Command failed: %s", type(e).__name__)
                try:
                    reply("Sorry, something went wrong with that command.")
                except Exception:
                    pass
        if updates:
            # Confirm the last batch so Telegram doesn't send it again.
            try:
                _api("getUpdates", offset=self.offset, timeout=0)
            except Exception:
                pass
        return changed

    def _save_state(self):
        try:
            Path(self.state_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.state_path).write_text(json.dumps(self.state))
        except OSError:
            pass

