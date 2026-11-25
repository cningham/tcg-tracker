"""Card condition: read it from eBay and compare it to a minimum.

eBay UK trading-card listings marked "Ungraded" carry a "Card Condition"
value: Near mint or better / Excellent / Very good / Poor. It's only in the
full item details, so we fetch those (once per listing) for candidates that
already passed the price check. Older or oddly listed items don't have it,
so the title is used as a fallback (NM, LP, MP, HP, damaged...).
"""
import re
from urllib.parse import quote

# Higher is better.
LEVELS = {4: "Near Mint", 3: "Excellent", 2: "Very Good", 1: "Poor"}
SHORT = {4: "NM", 3: "EX", 2: "VG", 1: "Poor"}

# Words a user might type for a minimum condition.
_WORDS = [  # (pattern, level), checked in order
    (r"near\s*mint|\bnm\b|\bmint\b", 4),
    (r"excellent|lightly\s*played|\blp\b", 3),
    (r"very\s*good|moderately\s*played|\bmp\b|\bvg\b|\bgood\b|\bplayed\b", 2),
    (r"\bpoor\b|heavily\s*played|\bhp\b|damaged", 1),
]

# Words trusted in listing titles. Deliberately strict: "ex" is a Pokémon card
# type and "HP" is printed on every Pokémon card, so neither counts here.
_TITLE = [
    (r"near\s*mint|\bnm\b|\bnm/m\b|\bmint\b", 4),
    (r"excellent|lightly\s*played|\blp\b", 3),
    (r"very\s*good|moderately\s*played|\bmp\b", 2),
    (r"\bpoor\b|heavily\s*played|damaged|\bdmg\b|crease", 1),
]


def parse_level(text):
    """'nm' / 'near mint' / 'excellent' / 'lp' ... -> 4..1, 'any' -> 0, else None."""
    t = (text or "").strip().lower()
    if t in ("any", "off", "none", "all", "0"):
        return 0
    if t in ("ex", "exc", "excellent", "lp", "lightly played"):
        return 3  # "ex" alone means Excellent here, not the Pokémon "ex" suffix
    for pattern, level in _WORDS:
        if re.search(pattern, t):
            return level
    return None


_DESCRIPTOR_IDS = {"400010": 4, "400011": 3, "400012": 2, "400013": 1}


def level_from_descriptor(text):
    t = (text or "").strip().lower()
    if t in _DESCRIPTOR_IDS:
        return _DESCRIPTOR_IDS[t]
    if "near mint" in t:
        return 4
    if "excellent" in t or "lightly" in t:
        return 3
    if "very good" in t or "moderately" in t:
        return 2
    if "poor" in t or "heavily" in t or "damaged" in t:
        return 1
    return None


def level_from_title(title):
    """Title fallback. Only trusts clear wording, and the worst match wins
    (e.g. 'NM but small crease' counts as Poor)."""
    t = (title or "").lower()
    found = [lvl for pat, lvl in _TITLE if re.search(pat, t)]
    return min(found) if found else None


class ConditionChecker:
    """Looks up a listing's condition, caching results for the run."""

    def __init__(self, ebay):
        self.ebay = ebay
        self.cache = {}
        self.stats = {}  # where conditions came from, for the run log

    def level(self, m):
        """(level or None, source) for a normalised listing."""
        if m["item_id"] in self.cache:
            return self.cache[m["item_id"]]
        result = (None, "")
        try:
            details = self.ebay.item(m["item_id"])
            for d in details.get("conditionDescriptors") or []:
                if "condition" in (d.get("name") or "").lower():
                    for v in d.get("values") or []:
                        lvl = level_from_descriptor(v.get("content"))
                        if lvl:
                            result = (lvl, "listing")
                            break
                if result[0]:
                    break
        except Exception:
            pass
        if not result[0]:
            lvl = level_from_title(m["title"])
            if lvl:
                result = (lvl, "title")
        self.cache[m["item_id"]] = result
        self.stats[result[1] or "unknown"] = self.stats.get(result[1] or "unknown", 0) + 1
        return result


def label(level, source=""):
    if not level:
        return "not stated"
    return LEVELS[level] + (" (from title)" if source == "title" else "")


def item_path(item_id):
    return f"/buy/browse/v1/item/{quote(item_id, safe='')}"
