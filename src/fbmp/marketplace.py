"""Marketplace URLs and HTML parsing.

Facebook's class names are obfuscated and change often, so parsing keys off stable
things only: links to /marketplace/item/<id>/, the visible text inside them, and
the [role="main"] region of a detail page.
"""

import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from .config import SearchConfig
from .models import Listing

ITEM_RE = re.compile(r"/marketplace/item/(\d+)")
PRICE_RE = re.compile(r"^(?:[A-Z]{0,3}\$|£|€)\s?(\d[\d,]*(?:\.\d{1,2})?)$")
MAX_PAGE_TEXT = 4000


def search_url(city: str, search: SearchConfig, days_since_listed: int) -> str:
    params: dict[str, str | int] = {
        "query": search.query,
        "daysSinceListed": days_since_listed,
        "sortBy": "creation_time_descend",
        "exact": "false",
    }
    if search.min_price is not None:
        params["minPrice"] = search.min_price
    if search.max_price is not None:
        params["maxPrice"] = search.max_price
    return f"https://www.facebook.com/marketplace/{city}/search?{urlencode(params)}"


def parse_price(text: str) -> float | None:
    text = text.strip()
    if text.lower() == "free":
        return 0.0
    m = PRICE_RE.match(text)
    return float(m.group(1).replace(",", "")) if m else None


def _lines(node) -> list[str]:
    out: list[str] = []
    for s in node.stripped_strings:
        if not out or out[-1] != s:
            out.append(s)
    return out


def parse_search_results(html: str) -> list[Listing]:
    """Extract listing cards from a Marketplace search results page."""
    soup = BeautifulSoup(html, "html.parser")
    listings: dict[str, Listing] = {}
    for a in soup.select('a[href*="/marketplace/item/"]'):
        m = ITEM_RE.search(a.get("href", ""))
        if not m or m.group(1) in listings:
            continue
        lines = _lines(a)
        # Cards read: current price, optional crossed-out old price, title, location.
        prices: list[float] = []
        while lines and (p := parse_price(lines[0])) is not None:
            prices.append(p)
            lines.pop(0)
        if not prices or not lines:
            continue
        img = a.find("img")
        listings[m.group(1)] = Listing(
            id=m.group(1),
            title=lines[0],
            price=prices[0],
            location=lines[1] if len(lines) > 1 else "",
            image_url=img.get("src") if img else None,
        )
    return list(listings.values())


def parse_detail(html: str) -> tuple[str, list[str]]:
    """Return (visible page text, photo URLs) for a listing detail page."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one('[role="main"]') or soup.body or soup
    for tag in main.select("script, style, noscript"):
        tag.decompose()
    text = "\n".join(_lines(main))[:MAX_PAGE_TEXT]
    og = soup.select_one('meta[property="og:description"]')
    if og and og.get("content") and og["content"] not in text:
        text = f"{og['content']}\n\n{text}"[:MAX_PAGE_TEXT]

    photos: list[str] = []
    for img in main.find_all("img"):
        src = img.get("src", "")
        if ("scontent" in src or "fbcdn" in src) and src not in photos:
            photos.append(src)
    return text, photos
