from fbmp.cli import sample_deal
from fbmp.models import Comp
from fbmp.notify import format_deal


def test_format_escapes_and_links():
    deal = sample_deal()
    deal.valuation.product = "Drill <b>&</b> case"
    text = format_deal(deal)
    assert "Drill &lt;b&gt;&amp;&lt;/b&gt; case" in text
    assert deal.listing.url in text
    assert text.count("•") == 3


def test_format_respects_limit():
    deal = sample_deal()
    deal.valuation.summary = "x" * 900
    deal.comps = [Comp(title="y" * 200, price=100, url="https://www.ebay.com/itm/" + "9" * 200)] * 3
    text = format_deal(deal)
    assert len(text) <= 1024
    assert "Open listing" in text
