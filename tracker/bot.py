"""Telegram commands for managing the watchlist from your phone.

    /add Charizard ex 199/165 50    watch a card, max £50 incl. postage
    /list                           show what's being watched
    /remove 2                       stop watching card 2
    /price 2 45                     change card 2's max to £45
    /help

Only messages from TELEGRAM_CHAT_ID are obeyed. Changes are saved to
watchlist.txt and committed to the repo, so they stick between runs.
"""
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
    parts = [" ".join(query_words), f"{price:g}"]
    if must:
        parts.append(f"must: {must}")
    if bin_only:
        parts.append("bin-only")
    return " | ".join(parts), None


def describe(line):
    parts = [p.strip() for p in line.split("|")]
    text = f"{parts[0]}: up to £{float(parts[1]):.2f}" if len(parts) > 1 else line
    extras = [p for p in parts[2:] if p]
    return text + (f" ({', '.join(extras)})" if extras else "")


def handle(text, lines):
    """Apply one command to a copy of the watchlist lines.
    Returns (reply text, new lines or None if nothing changed)."""
    text = (text or "").strip()
    cmd, _, rest = text.partition(" ")
    cmd = cmd.lower().split("@")[0]
    lines = list(lines)
    idx = card_lines(lines)

    if cmd == "/add":
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


class Bot:
    def __init__(self, path="watchlist.txt"):
        self.path = path
        self.offset = None

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
                answer, new_lines = handle(text, read_lines(self.path))
                if new_lines is not None:
                    save(self.path, "\n".join(new_lines) + "\n",
                         f"Watchlist: {text.split()[0]} via Telegram")
                    changed = True
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

