from pathlib import Path

from fbmp.config import SearchConfig
from fbmp.marketplace import parse_detail, parse_price, parse_search_results, search_url

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_price():
    assert parse_price("$60") == 60
    assert parse_price("$1,250.50") == 1250.50
    assert parse_price("CA$40") == 40
    assert parse_price("Free") == 0
    assert parse_price("Just listed") is None


def test_search_results():
    listings = parse_search_results((FIXTURES / "search.html").read_text())
    by_id = {l.id: l for l in listings}
    # 4444444444 has no price; 6666666666 is marked Pending.
    assert list(by_id) == ["1111111111", "2222222222", "3333333333", "5555555555"]

    drill = by_id["1111111111"]
    assert drill.price == 60  # current price, not the crossed-out $90
    assert drill.title == "DeWalt 20V drill w/ 2 batteries"
    assert drill.location == "Seattle, WA"
    assert drill.image_url.endswith("drill.jpg")
    assert drill.url == "https://www.facebook.com/marketplace/item/1111111111/"

    assert by_id["2222222222"].price == 1250.50
    assert by_id["3333333333"].price == 0

    badged = by_id["5555555555"]  # "Just listed" badge before the price
    assert badged.price == 110 and badged.title == "Milwaukee M18 Hackzall (Tool-Only)"
    assert badged.location == "Oklahoma City, OK"


def test_detail():
    text, photos = parse_detail((FIXTURES / "detail.html").read_text())
    assert text.startswith("Works great, barely used.")
    assert "Used - Good" in text
    assert "should not appear" not in text and "color:red" not in text
    assert photos == [
        "https://scontent-sea1-1.xx.fbcdn.net/v/photo1.jpg",
        "https://scontent-sea1-1.xx.fbcdn.net/v/photo2.jpg",
    ]


def test_search_url():
    url = search_url("seattle", SearchConfig(query="dewalt drill", max_price=150), days_since_listed=1)
    assert url.startswith("https://www.facebook.com/marketplace/seattle/search?")
    assert "query=dewalt+drill" in url and "maxPrice=150" in url and "minPrice" not in url
    assert "sortBy=creation_time_descend" in url
    assert search_url("", SearchConfig(query="ps5"), 1).startswith("https://www.facebook.com/marketplace/search?")
