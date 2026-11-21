# TCG Tracker

Watches eBay UK for raw Pokémon / Cyberpunk cards and pings you on Telegram and/or email
when one is listed under your max price (price + postage). Runs free on GitHub Actions, or locally on your PC.

- **Buy It Now:** alerted as soon as one under your max appears.
- **Auctions:** alerted only when there are 10 minutes or less left and current bid + postage is under your max.
- **Graded slabs are skipped** (eBay's "Graded" condition, plus titles with PSA/CGC/BGS/etc.). Proxies, customs and lots are skipped too.
- You only get one alert per listing.

## Run it in the cloud (free, laptop can be off)

The tracker runs on GitHub Actions. In a **public** repo this is free with no minute limit.
Only the code is public: your watchlist, keys and alerts stay private, and the run logs only show counts.

Checks happen every 5 minutes. GitHub sometimes starts scheduled runs late, so expect the odd gap of 5 to 15 minutes.

### 1. Get the keys
- **eBay:** at https://developer.ebay.com, create a **Production** keyset and copy the App ID (Client ID) and Cert ID (Client Secret).
  If eBay asks about "marketplace account deletion notifications", choose the exemption ("I do not persist eBay data").
- **Telegram:** message **@BotFather**, send `/newbot`, and copy the token. Then send your new bot any message and open
  `https://api.telegram.org/bot<TOKEN>/getUpdates` in your browser. The number after `"chat":{"id":` is your chat id.
- **Email (optional, Gmail):** turn on 2-step verification and create an App Password at https://myaccount.google.com/apppasswords.

### 2. Add them to GitHub
In the repo, go to **Settings → Secrets and variables → Actions**.

**Secrets** tab, **New repository secret** for each one you use:
`EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO`

**Variables** tab, **New repository variable** named `WATCHLIST`, one card per line:

```
Charizard ex 199 | 50 | must: 199/165 | not: japanese, jumbo
Pikachu 025 151 | 12.50
Johnny Silverhand | 8 | bin-only
```

Each line is `eBay search words | max £ including postage | options`. The options are:
- `must: a, b`: the listing title must contain all of these (great for card numbers like `199/165`).
- `not: x, y`: skip titles containing any of these.
- `bin-only`: ignore auctions for this card.

To change your watchlist later, edit that variable (it works from the GitHub mobile app or the website). The next run picks it up.

### 3. Turn it on
Go to the **Actions** tab, enable workflows if asked, open **Watch eBay**, and press **Run workflow** with
"Only send a test alert" ticked. You should get a Telegram message (and an email if set up).
After that it runs by itself every 30 minutes, checking every 5.

Optional variables: `EBAY_ITEM_LOCATION` (e.g. `GB` for UK sellers only) and `AUCTION_WINDOW_MINUTES` (default 10).

## Run it on your PC instead (Windows)

There's also a local version with a web page and Collectr CSV import. It only works while your PC is on.

### Setup


1. **Python:** install Python 3.11+ from https://www.python.org/downloads/ and tick **"Add python.exe to PATH"**.
2. **eBay key (free):**
   1. Sign up at https://developer.ebay.com (you can use your normal eBay login).
   2. Go to **Hi <name> → Application Keys**, create a keyset, and use the **Production** one.
      eBay may ask you to opt out of "marketplace account deletion notifications" for a production key: choose the exemption ("I do not persist eBay data").
   3. Copy the **App ID (Client ID)** and **Cert ID (Client Secret)**.
3. **Run `start.bat`** (double-click). The first time it installs things and opens `.env` in Notepad.
   Paste the two eBay values after `EBAY_CLIENT_ID=` and `EBAY_CLIENT_SECRET=`, then save.
   `.env` stays on your PC. Don't send it to anyone.
4. **Telegram (recommended):**
   1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts, and copy the token into `TELEGRAM_BOT_TOKEN=` in `.env`.
   2. Send your new bot any message (e.g. "hi").
   3. In this folder, run `.venv\Scripts\python telegram_chat_id.py` and copy the `TELEGRAM_CHAT_ID=...` line into `.env`.
5. **Email (optional, Gmail):** turn on 2-step verification, create an App Password at
   https://myaccount.google.com/apppasswords, and fill in `SMTP_USER` (your Gmail), `SMTP_PASSWORD` (the app password) and `EMAIL_TO`.
6. Run **`start.bat`** again. Your browser opens at http://localhost:5055. Press **Send test alert** to check Telegram/email.

Leave the black window open: closing it stops the tracker.
To start it automatically when Windows starts, press `Win+R`, type `shell:startup`, and put a shortcut to `start.bat` in that folder.

### Adding cards (local version)

- **By hand:** fill in "Add a card". The eBay search is all keywords, e.g. `Charizard ex 199`.
  Use **Title must have** to pin the exact card (e.g. `199/165`) and **Title must not have** for things like `japanese, jumbo`.
- **From Collectr:** export your collection or watchlist as CSV in the Collectr app, then use **Import from Collectr**,
  tick the cards you want, and give each one a max price. If the importer can't read your file,
  send me the column names (just the header row) and I'll adjust it.

### Notes (local version)

- The free eBay API allows 5,000 calls a day. Each card uses 2 calls per check (1 without auctions), every 5 minutes,
  so roughly **8 cards with auctions** or **17 without** fit. The page shows your current estimate.
  Change `CHECK_EVERY_MINUTES` in `.env` if you want to watch more.
- Category is "CCG Individual Cards" (183454). If a card never shows up, blank out `EBAY_CATEGORY_ID` in `.env`.
- Data is stored in `tracker.db` in this folder.
