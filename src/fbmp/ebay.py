"""eBay Browse API client for price comps.

The Browse API only returns active listings (sold prices need the restricted
Marketplace Insights API), so callers discount these prices with
ThresholdConfig.active_to_sold_ratio.
"""

import base64
import time

import httpx

from .models import Comp

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayClient:
    def __init__(self, client_id: str, client_secret: str, http: httpx.Client | None = None):
        self._basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._http = http or httpx.Client(timeout=20)
        self._token: str | None = None
        self._token_expires = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        r = self._http.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {self._basic}"},
            data={"grant_type": "client_credentials", "scope": SCOPE},
        )
        r.raise_for_status()
        body = r.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + body.get("expires_in", 7200)
        return self._token

    def search(self, query: str, limit: int = 50) -> list[Comp]:
        r = self._http.get(
            SEARCH_URL,
            params={
                "q": query,
                "limit": limit,
                # Fixed-price only: auction bids mid-flight aren't a price signal.
                "filter": "buyingOptions:{FIXED_PRICE},priceCurrency:USD,deliveryCountry:US",
            },
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            },
        )
        r.raise_for_status()
        return parse_search_response(r.json())


def parse_search_response(data: dict) -> list[Comp]:
    comps: list[Comp] = []
    for item in data.get("itemSummaries", []):
        price = item.get("price") or {}
        if price.get("currency") != "USD" or "value" not in price:
            continue
        shipping = 0.0
        options = item.get("shippingOptions") or []
        if options and (cost := (options[0].get("shippingCost") or {}).get("value")) is not None:
            shipping = float(cost)
        comps.append(
            Comp(
                title=item.get("title", ""),
                price=float(price["value"]),
                shipping=shipping,
                condition=item.get("condition", ""),
                url=item.get("itemWebUrl", ""),
            )
        )
    return comps
