import json
from pathlib import Path

from fbmp.ebay import parse_search_response


def test_parse_search_response():
    data = json.loads((Path(__file__).parent / "fixtures" / "ebay_search.json").read_text())
    comps = parse_search_response(data)
    assert len(comps) == 2  # the CAD listing is skipped
    assert comps[0].price == 149.99 and comps[0].shipping == 12.50 and comps[0].total == 162.49
    assert comps[1].shipping == 0  # no shippingOptions
    assert comps[1].condition == "Pre-owned"


def test_empty_response():
    assert parse_search_response({"total": 0}) == []
