"""Read a Collectr CSV export.

Collectr's exact column names aren't documented publicly, so this looks for the
usual suspects and falls back gracefully. If your export uses different headers,
add them to the lists below.
"""
import csv
import io
import re

COLUMNS = {
    "name": ["product name", "name", "card name", "card", "title", "product"],
    "game": ["category", "game", "tcg", "category name"],
    "set_name": ["set", "set name", "group", "group name", "expansion", "series"],
    "number": ["card number", "number", "no", "no.", "collector number", "#"],
    "market_price": ["market price", "price", "market value", "value",
                     "market price (gbp)", "market price (usd)", "current value"],
    "condition": ["condition", "grade", "card condition"],
}


def _find(headers, wanted):
    lower = {h.strip().lower(): h for h in headers if h}
    for w in wanted:
        if w in lower:
            return lower[w]
    return None


def _price(text):
    if not text:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", str(text))
    return float(m.group(0).replace(",", "")) if m else None


def suggest_query(name, number="", set_name=""):
    """A sensible default eBay search for a card."""
    name = re.sub(r"\s*[\(\[].*?[\)\]]", "", name).strip()  # drop "(Secret Rare)" etc.
    num = number.split("/")[0].strip() if number else ""
    parts = [name]
    if num and num not in name:
        parts.append(num)
    return " ".join(parts)


def parse(file_bytes):
    """Return (rows, mapping). Each row is a dict with our field names."""
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    mapping = {k: _find(headers, v) for k, v in COLUMNS.items()}
    rows = []
    for raw in reader:
        get = lambda k: (raw.get(mapping[k]) or "").strip() if mapping[k] else ""
        name = get("name")
        if not name:
            continue
        number = get("number")
        rows.append({
            "name": name,
            "game": get("game"),
            "set_name": get("set_name"),
            "number": number,
            "market_price": _price(get("market_price")),
            "condition": get("condition"),
            "query": suggest_query(name, number, get("set_name")),
        })
    return rows, mapping, headers
