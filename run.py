"""Start TCG Tracker: the eBay checker in the background plus the local web page."""
import logging
import threading
import webbrowser

from tracker import checker, config, db
from tracker.web import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main():
    db.init()
    stop = threading.Event()
    threading.Thread(target=checker.loop, args=(stop,), daemon=True).start()
    url = f"http://localhost:{config.WEB_PORT}"
    print(f"\n  TCG Tracker running at {url}  (close this window to stop)\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    # 127.0.0.1 only: the page is not reachable from other devices on your network.
    app.run(host="127.0.0.1", port=config.WEB_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
