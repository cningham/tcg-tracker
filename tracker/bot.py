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
    "/remove 2  (stop watching card 2)\n"
    "/price 2 45  (change card 2's max to £45)\n\n"
    "Add 'bin' at the end of /add to skip auctions, e.g. /add Pikachu 025/165 12 bin"
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
        {"command": "remove", "description": "Stop watching a card: /remove 2"},
        {"command": "price", "description": "Change a max price: /price 2 45"},
        {"command": "help", "description": "How to use me"},
    ])


def reply(text):
    _api("sendMessage", chat_id=config.TELEGRAM_CHAT_ID, text=text,
         disable_web_page_preview=True)


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
    words = text.split()
    bin_only = False
    if words and words[-1].lower() in ("bin", "bin-only", "buyitnow"):
        bin_only = True
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


def name_from_link(url):
    """Best guess at the card name behind a shared link (e.g. from Collectr)."""
    final_url = url
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
        final_url = r.url
        page = r.text[:400000]
        log.info("link fetch: status %s, %d bytes", r.status_code, len(page))
        for cand in (_meta(page, "og:title", "twitter:title"),
                     *re.findall(r'"@type"\s*:\s*"Product".{0,400}?"name"\s*:\s*"([^"]+)"', page, re.S)[:1],
                     *(re.findall(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)[:1])):
            name = _clean_title(cand)
            if name:
                return name
    except Exception as e:
        log.info("link fetch failed: %s", type(e).__name__)
    # Fall back to the words in the link itself, e.g. /product/charizard-ex-199-165
    from urllib.parse import unquote, urlparse
    for seg in reversed([x for x in urlparse(final_url).path.split("/") if x]):
        seg = unquote(seg)
        if re.search(r"[a-zA-Z]{3,}", seg) and not re.fullmatch(r"[0-9a-f-]{20,}", seg):
            if seg.lower() in ("product", "products", "explore", "card", "cards", "item", "portfolio"):
                continue
            return re.sub(r"[-_]+", " ", seg).strip()
    return ""


def _price_from(text):
    m = re.fullmatch(r"£?\s*(\d+(?:[.,]\d{1,2})?)\s*(?:£|gbp)?", text.strip(), re.I)
    return float(m.group(1).replace(",", ".")) if m else None


def describe(line):
    parts = [p.strip() for p in line.split("|")]
    text = f"{parts[0]}: up to £{float(parts[1]):.2f}" if len(parts) > 1 else line
    extras = [p for p in parts[2:] if p]
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
        name = name_from_link(url) or re.sub(r"(?i)check out|on collectr|collectr|!", " ", rest).strip()
        if not name:
            return ("I couldn't read the card name from that link. Send it like "
                    "/add Charizard ex 199/165 50 instead."), None
        if price is None:
            state["pending"] = name
            return (f"Found: {name}\nWhat's the most you'd pay, postage included? "
                    "Reply with just the number, e.g. 25"), None
        text = f"/add {name} {price:g}"
    elif state.get("pending") and _price_from(text) is not None:
        text = f"/add {state.pop('pending')} {_price_from(text):g}"

    cmd, _, rest = text.partition(" ")
    cmd = cmd.lower().split("@")[0]
    lines = list(lines)
    idx = card_lines(lines)

    if cmd == "/add":
        state.pop("pending", None)
        line, err = line_for_add(rest)
        if err:
            return err, None
        lines.append(line)
        return f"Added card {len(idx) + 1}: {describe(line)}\nI'll message you when one is listed under that price.", lines

    if cmd == "/list":
        if not idx:
            return "You're not watching any cards yet.\n\n" + HELP, None
        out = [f"{n}. {describe(lines[i])}" for n, i in enumerate(idx, 1)]
        if os.environ.get("WATCHLIST", "").strip():
            out.append("\nNote: a WATCHLIST secret is set on GitHub, and it overrides this list.")
        return "\n".join(out), None

    if cmd in ("/remove", "/delete"):
        try:
            n = int(rest.strip())
            i = idx[n - 1]
            assert n >= 1
        except (ValueError, IndexError, AssertionError):
            return "Which card? Send /list to see the numbers, then e.g. /remove 2", None
        removed = lines.pop(i)
        return f"Stopped watching: {describe(removed)}", lines

    if cmd == "/price":
        try:
            n_s, p_s = rest.split()
            n, price = int(n_s), float(p_s.replace("£", ""))
            i = idx[n - 1]
            assert n >= 1
        except (ValueError, IndexError, AssertionError):
            return "Send it like /price 2 45 (card 2, new max £45). /list shows the numbers.", None
        parts = [p.strip() for p in lines[i].split("|")]
        parts[1] = f"{price:g}"
        lines[i] = " | ".join(parts)
        return f"Updated: {describe(lines[i])}", lines

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

