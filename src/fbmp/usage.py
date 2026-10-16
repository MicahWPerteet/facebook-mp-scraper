"""Claude token usage and cost tracking."""

from dataclasses import dataclass

# USD per million tokens (input, output). Thinking tokens are billed as output.
# Includes the models the server-side refusal fallback may route to.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-4-8": (5.00, 25.00),
}


@dataclass
class Usage:
    step: str  # "triage" | "valuation"
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def cost(self) -> float | None:
        """USD cost, or None for a model missing from PRICES."""
        price = PRICES.get(self.model)
        if price is None:
            return None
        return (self.input_tokens * price[0] + self.output_tokens * price[1]) / 1_000_000


def usage_from_response(step: str, resp) -> Usage:
    u = resp.usage
    # No prompt caching is configured, but count cache tokens at the input price if they ever appear.
    input_tokens = u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0)
    return Usage(step=step, model=resp.model, input_tokens=input_tokens, output_tokens=u.output_tokens)


class CostTracker:
    """Collects the Claude calls made during one cycle."""

    def __init__(self, sink=None):
        self.calls: list[Usage] = []
        self._sink = sink  # e.g. DB.record_usage, to persist each call

    def record(self, step: str, resp) -> None:
        usage = usage_from_response(step, resp)
        self.calls.append(usage)
        if self._sink:
            self._sink(usage)

    @property
    def total(self) -> float:
        return sum(c.cost or 0.0 for c in self.calls)

    def summary(self) -> str:
        parts = []
        for step in dict.fromkeys(c.step for c in self.calls):
            calls = [c for c in self.calls if c.step == step]
            tokens_in = sum(c.input_tokens for c in calls)
            tokens_out = sum(c.output_tokens for c in calls)
            cost = sum(c.cost or 0.0 for c in calls)
            unpriced = " (some calls unpriced)" if any(c.cost is None for c in calls) else ""
            parts.append(
                f"{step} {len(calls)} call{'s' if len(calls) != 1 else ''}, "
                f"{tokens_in / 1000:.1f}k in / {tokens_out / 1000:.1f}k out, ${cost:.4f}{unpriced}"
            )
        return f"${self.total:.4f} ({'; '.join(parts) or 'no calls'})"
