import datetime as dt

import pytest

from fbmp.cli import in_quiet_hours, seconds_until_hour
from fbmp.config import ScheduleConfig, ThresholdConfig
from fbmp.evaluate import compute_deal, should_alert
from fbmp.models import Comp, Listing, Valuation

T = ThresholdConfig(min_profit=75, min_margin=0.4, ebay_fee_rate=0.10, active_to_sold_ratio=0.8, min_comps=3)


def valuation(**kw):
    base = dict(product="X", matching_comps=[1, 2, 3], condition="good", shipping_estimate=10,
                confidence="high", red_flags=[], summary="")
    return Valuation(**{**base, **kw})


COMPS = [Comp(title=f"c{i}", price=p, shipping=s) for i, (p, s) in enumerate([(190, 10), (240, 10), (290, 10), (5, 0)])]


def test_compute_deal_math():
    deal = compute_deal(Listing(id="1", title="t", price=50), valuation(), COMPS, T)
    # median total of comps 1-3 = 250; * 0.8 = 200; * (1 - 0.10) = 180; - 10 shipping = 170
    assert deal.resale == 200 and deal.net == 170 and deal.profit == 120
    assert deal.margin == pytest.approx(2.4)
    assert len(deal.comps) == 3 and should_alert(deal, T)


def test_out_of_range_and_duplicate_comp_numbers_ignored():
    deal = compute_deal(Listing(id="1", title="t", price=50), valuation(matching_comps=[1, 1, 9, 0]), COMPS, T)
    assert len(deal.comps) == 1 and not should_alert(deal, T)


@pytest.mark.parametrize(
    "price, kw, expected",
    [
        (120, {}, False),  # profit $50 < $75
        (50, {"confidence": "low"}, False),
        (50, {"condition": "for_parts"}, False),
        (0, {}, True),  # free item: margin is None, profit alone decides
        (130, {"matching_comps": [2, 3, 3]}, False),  # only two distinct comps
    ],
)
def test_should_alert(price, kw, expected):
    deal = compute_deal(Listing(id="1", title="t", price=price), valuation(**kw), COMPS, T)
    assert should_alert(deal, T) is expected


def test_no_matching_comps():
    deal = compute_deal(Listing(id="1", title="t", price=50), valuation(matching_comps=[]), COMPS, T)
    assert deal.resale == 0 and not should_alert(deal, T)


def test_quiet_hours():
    wrap = ScheduleConfig(quiet_start_hour=23, quiet_end_hour=8)
    assert in_quiet_hours(23, wrap) and in_quiet_hours(3, wrap)
    assert not in_quiet_hours(8, wrap) and not in_quiet_hours(15, wrap)
    same_day = ScheduleConfig(quiet_start_hour=1, quiet_end_hour=6)
    assert in_quiet_hours(1, same_day) and not in_quiet_hours(6, same_day)
    assert not in_quiet_hours(3, ScheduleConfig(quiet_start_hour=0, quiet_end_hour=0))


def test_seconds_until_hour():
    assert seconds_until_hour(dt.datetime(2026, 1, 1, 23, 30), 8) == 8.5 * 3600
    assert seconds_until_hour(dt.datetime(2026, 1, 1, 7, 0), 8) == 3600
