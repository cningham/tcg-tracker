"""eBay Browse API client (official API, no scraping).

Docs: https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
"""
import base64
import time
from datetime import datetime, timedelta, timezone

import requests

from . import config

API = "https://api.ebay.com"
SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayError(Exception):
    pass


class Ebay:
    def __init__(self, client_id=None, client_secret=None, api=API, session=None):
        self.client_id = client_id or config.EBAY_CLIENT_ID
        self.client_secret = client_secret or config.EBAY_CLIENT_SECRET
        self.api = api
        self.http = session or requests.Session()
        self._token = None
        self._token_expires = 0.0

    # -- auth -------------------------------------------------------------
    def _get_token(self):
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        if not (self.client_id and self.client_secret):
            raise EbayError("EBAY_CLIENT_ID / EBAY_CLIENT_SECRET are not set")
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = self.http.post(
            f"{self.api}/identity/v1/oauth2/token",
            headers={"Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "scope": SCOPE},
            timeout=20,
        )
        if r.status_code != 200:
            raise EbayError(f"eBay login failed ({r.status_code}): {r.text[:300]}")
        body = r.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + int(body.get("expires_in", 7200))
        return self._token

    # -- search -----------------------------------------------------------
    def search(self, query, max_price, kind="FIXED_PRICE", ending_within_minutes=None, limit=50):
        """Return a list of normalised listings under max_price (item price only;
        postage is added afterwards by the checker)."""
        filters = [
            f"price:[..{max_price:.2f}]",
            f"priceCurrency:{config.EBAY_CURRENCY}",
            f"buyingOptions:{{{kind}}}",
        ]
        if config.EBAY_DELIVERY_COUNTRY:
            filters.append(f"deliveryCountry:{config.EBAY_DELIVERY_COUNTRY}")
        if config.EBAY_ITEM_LOCATION:
            filters.append(f"itemLocationCountry:{config.EBAY_ITEM_LOCATION}")
        if ending_within_minutes is not None:
            end = datetime.now(timezone.utc) + timedelta(minutes=ending_within_minutes)
            filters.append(f"itemEndDate:[..{end.strftime('%Y-%m-%dT%H:%M:%SZ')}]")

        params = {
            "q": query,
            "filter": ",".join(filters),
            "sort": "endingSoonest" if kind == "AUCTION" else "price",
            "limit": str(limit),
        }
        if config.EBAY_CATEGORY_ID:
            params["category_ids"] = config.EBAY_CATEGORY_ID

        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "X-EBAY-C-MARKETPLACE-ID": config.EBAY_MARKETPLACE,
        }
        if config.EBAY_DELIVERY_COUNTRY:
            # Makes eBay return postage costs for this country.
            headers["X-EBAY-C-ENDUSERCTX"] = f"contextualLocation=country%3D{config.EBAY_DELIVERY_COUNTRY}"

        r = self.http.get(f"{self.api}/buy/browse/v1/item_summary/search",
                          params=params, headers=headers, timeout=30)
        if r.status_code == 401:
            self._token = None  # expired, retry once
            headers["Authorization"] = f"Bearer {self._get_token()}"
            r = self.http.get(f"{self.api}/buy/browse/v1/item_summary/search",
                              params=params, headers=headers, timeout=30)
        if r.status_code != 200:
            raise EbayError(f"eBay search failed ({r.status_code}): {r.text[:300]}")
        return [normalise(i, kind) for i in r.json().get("itemSummaries", [])]


def _money(obj):
    if not obj:
        return None
    try:
        return float(obj.get("value"))
    except (TypeError, ValueError):
        return None


def normalise(item, kind):
    if kind == "AUCTION":
        price = _money(item.get("currentBidPrice")) or _money(item.get("price")) or 0.0
    else:
        price = _money(item.get("price")) or 0.0

    postage = None
    for opt in item.get("shippingOptions") or []:
        cost = _money(opt.get("shippingCost"))
        if cost is not None and (postage is None or cost < postage):
            postage = cost

    image = (item.get("image") or {}).get("imageUrl")
    currency = ((item.get("currentBidPrice") if kind == "AUCTION" else None)
                or item.get("price") or {}).get("currency", config.EBAY_CURRENCY)
    return {
        "item_id": item.get("itemId", ""),
        "title": item.get("title", ""),
        "price": price,
        "postage": postage,               # None = eBay didn't say
        "total": price + (postage or 0.0),
        "currency": currency,
        "kind": kind,
        "url": item.get("itemWebUrl", ""),
        "image": image,
        "ends_at": item.get("itemEndDate"),
        "condition": item.get("condition", ""),
        "condition_id": str(item.get("conditionId", "")),
        "bids": item.get("bidCount"),
    }
