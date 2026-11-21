"""SQLite storage: watched cards, alerts already sent, and recent matches."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    game TEXT NOT NULL DEFAULT '',
    set_name TEXT NOT NULL DEFAULT '',
    number TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL,
    max_price REAL NOT NULL,
    must_include TEXT NOT NULL DEFAULT '',
    exclude TEXT NOT NULL DEFAULT '',
    include_auctions INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    market_price REAL,
    last_checked TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
    card_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    title TEXT NOT NULL,
    total REAL NOT NULL,
    currency TEXT NOT NULL,
    kind TEXT NOT NULL,
    url TEXT NOT NULL,
    image TEXT,
    ends_at TEXT,
    found_at TEXT NOT NULL,
    PRIMARY KEY (card_id, item_id)
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as c:
        c.executescript(SCHEMA)


def list_cards(enabled_only=False):
    sql = "SELECT * FROM cards"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY game, name"
    with connect() as c:
        return [dict(r) for r in c.execute(sql)]


def get_card(card_id):
    with connect() as c:
        r = c.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return dict(r) if r else None


def add_card(name, query, max_price, game="", set_name="", number="",
             must_include="", exclude="", include_auctions=True, market_price=None):
    with connect() as c:
        cur = c.execute(
            """INSERT INTO cards (name, game, set_name, number, query, max_price,
                   must_include, exclude, include_auctions, market_price, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (name, game, set_name, number, query, max_price, must_include,
             exclude, int(include_auctions), market_price, now_iso()),
        )
        return cur.lastrowid


FIELDS = {"name", "game", "set_name", "number", "query", "max_price", "must_include",
          "exclude", "include_auctions", "enabled", "market_price"}


def update_card(card_id, **fields):
    fields = {k: v for k, v in fields.items() if k in FIELDS}
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE cards SET {sets} WHERE id = ?", (*fields.values(), card_id))


def delete_card(card_id):
    with connect() as c:
        c.execute("DELETE FROM matches WHERE card_id = ?", (card_id,))
        c.execute("DELETE FROM cards WHERE id = ?", (card_id,))


def mark_checked(card_id, error=None):
    with connect() as c:
        c.execute("UPDATE cards SET last_checked = ?, last_error = ? WHERE id = ?",
                  (now_iso(), error, card_id))


def record_match(card_id, m):
    """Save a match. Returns True if it is new (so an alert should go out)."""
    with connect() as c:
        cur = c.execute(
            """INSERT OR IGNORE INTO matches
               (card_id, item_id, title, total, currency, kind, url, image, ends_at, found_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (card_id, m["item_id"], m["title"], m["total"], m["currency"], m["kind"],
             m["url"], m.get("image"), m.get("ends_at"), now_iso()),
        )
        return cur.rowcount == 1


def recent_matches(limit=50):
    with connect() as c:
        return [dict(r) for r in c.execute(
            """SELECT m.*, c.name AS card_name, c.max_price FROM matches m
               JOIN cards c ON c.id = m.card_id
               ORDER BY m.found_at DESC LIMIT ?""", (limit,))]
