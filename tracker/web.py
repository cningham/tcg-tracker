"""Local web page for managing the watchlist (http://localhost:5055)."""
import json
import threading

from flask import Flask, flash, redirect, render_template, request, url_for

from . import checker, collectr, config, db, notify

app = Flask(__name__)
app.secret_key = "local-only"


def _float(v, default=None):
    try:
        return float(str(v).replace("£", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


@app.route("/")
def index():
    cards = db.list_cards()
    return render_template(
        "index.html",
        cards=cards,
        matches=db.recent_matches(),
        channels=notify.channels(),
        ebay_ready=bool(config.EBAY_CLIENT_ID and config.EBAY_CLIENT_SECRET),
        calls=checker.calls_per_day(cards),
        cfg=config,
    )


@app.post("/cards")
def add_card():
    f = request.form
    name = f.get("name", "").strip()
    max_price = _float(f.get("max_price"))
    if not name or max_price is None:
        flash("Card name and max price are required.")
        return redirect(url_for("index"))
    db.add_card(
        name=name,
        game=f.get("game", "").strip(),
        number=f.get("number", "").strip(),
        query=f.get("query", "").strip() or collectr.suggest_query(name, f.get("number", "")),
        max_price=max_price,
        must_include=f.get("must_include", "").strip(),
        exclude=f.get("exclude", "").strip(),
        include_auctions="include_auctions" in f,
    )
    flash(f"Watching {name}.")
    return redirect(url_for("index"))


@app.post("/cards/<int:card_id>")
def update_card(card_id):
    f = request.form
    fields = {
        "query": f.get("query", "").strip(),
        "must_include": f.get("must_include", "").strip(),
        "exclude": f.get("exclude", "").strip(),
        "include_auctions": int("include_auctions" in f),
        "enabled": int("enabled" in f),
    }
    mp = _float(f.get("max_price"))
    if mp is not None:
        fields["max_price"] = mp
    if not fields["query"]:
        fields.pop("query")
    db.update_card(card_id, **fields)
    flash("Saved.")
    return redirect(url_for("index"))


@app.post("/cards/<int:card_id>/delete")
def delete_card(card_id):
    db.delete_card(card_id)
    flash("Removed.")
    return redirect(url_for("index"))


@app.post("/check")
def check_now():
    threading.Thread(target=checker.run_once, daemon=True).start()
    flash("Checking eBay now. Refresh in a few seconds.")
    return redirect(url_for("index"))


@app.post("/test-alert")
def test_alert():
    if not notify.channels():
        flash("No alert channel set up yet. Add Telegram or email settings to .env and restart.")
    else:
        results = notify.send("Test alert", "TCG Tracker test alert. If you can read this, alerts work.")
        flash("; ".join(f"{ch}: {'sent' if err is None else 'FAILED - ' + err}" for ch, err in results))
    return redirect(url_for("index"))


@app.route("/import", methods=["GET", "POST"])
def import_csv():
    if request.method == "GET":
        return render_template("import.html", rows=None)
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose your Collectr CSV export first.")
        return redirect(url_for("import_csv"))
    rows, mapping, headers = collectr.parse(file.read())
    if not rows:
        flash(f"Couldn't find any cards. Columns in that file: {', '.join(headers) or 'none'}")
        return redirect(url_for("import_csv"))
    return render_template("import.html", rows=rows, mapping=mapping, headers=headers,
                           rows_json=json.dumps(rows))


@app.post("/import/confirm")
def import_confirm():
    rows = json.loads(request.form.get("rows_json", "[]"))
    added = 0
    for i, row in enumerate(rows):
        if f"pick_{i}" not in request.form:
            continue
        max_price = _float(request.form.get(f"max_{i}"))
        if max_price is None:
            continue
        db.add_card(
            name=row["name"], game=row.get("game", ""), set_name=row.get("set_name", ""),
            number=row.get("number", ""),
            query=request.form.get(f"query_{i}", "").strip() or row["query"],
            max_price=max_price, market_price=row.get("market_price"),
            include_auctions=True,
        )
        added += 1
    flash(f"Added {added} card(s). Cards without a max price were skipped.")
    return redirect(url_for("index"))
