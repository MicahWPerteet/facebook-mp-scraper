from types import SimpleNamespace

import pytest

from fbmp.db import DB
from fbmp.usage import CostTracker, Usage


def response(model, input_tokens, output_tokens, cache_read=None):
    usage = SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_creation_input_tokens=None, cache_read_input_tokens=cache_read,
    )
    return SimpleNamespace(model=model, usage=usage)


def test_cost():
    assert Usage("valuation", "claude-sonnet-5-5", 8000, 2000).cost == pytest.approx(0.036)
    assert Usage("triage", "claude-haiku-5-5", 2000, 3000).cost == pytest.approx(0.0017)
    assert Usage("x", "some-future-model", 1000, 1000).cost is None


def test_tracker_persists_and_summarizes():
    db = DB(":memory:")
    costs = CostTracker(sink=db.record_usage)
    costs.record("triage", response("claude-haiku-5-5", 2000, 3000))
    costs.record("valuation", response("claude-sonnet-5-5", 7000, 2000, cache_read=1000))
    costs.record("valuation", response("some-future-model", 1000, 1000))

    assert costs.total == pytest.approx(0.0017 + 0.036)
    assert db.cost_since(0) == pytest.approx(costs.total)
    summary = costs.summary()
    assert summary.startswith("$0.0377 (triage 1 call, 2.0k in / 3.0k out, $0.0017; valuation 2 calls")
    assert "some calls unpriced" in summary
