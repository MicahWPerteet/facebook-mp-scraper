"""Claude triage + valuation, and the profit math that decides whether to alert."""

import base64
import json
import logging
import statistics

import anthropic

from .config import ThresholdConfig
from .models import CONFIDENCE_RANK, Comp, Deal, Listing, TriageItem, TriageResult, Valuation

log = logging.getLogger(__name__)

TRIAGE_MODEL = "claude-haiku-5-5"
VALUATION_MODEL = "claude-sonnet-5-5"
TRIAGE_BATCH = 25

TRIAGE_SYSTEM = """\
You screen Facebook Marketplace listings for someone who buys items locally and resells them on eBay.
Target categories: {categories}.

Keep a listing only if it is plausibly a specific, identifiable product in those categories that sells \
on eBay, at an asking price low enough that a resale profit is possible.
Reject: wanted/ISO posts, items described as broken or for parts, bundles too vague to identify, \
generic or unbranded goods, services, rentals, and anything outside the target categories.

For every listing, return one item with its id. For kept listings, give the most specific product name \
you can (brand, model, variant) and a 3-6 word eBay search query for the same product, with no \
condition words or punctuation."""

VALUATION_SYSTEM = """\
You value Facebook Marketplace listings for resale on eBay.

You get the Marketplace listing (title, asking price, the visible text of its page, and photos) and a \
numbered list of current eBay fixed-price listings found by searching for the product.

1. Identify the exact product from the title, page text and photos.
2. Choose the eBay listings that are the same product in a comparable condition and configuration. \
Exclude different models, bundles with significant extras, accessories, parts-only listings and \
obvious price outliers. Return their numbers in matching_comps.
3. Judge the Marketplace item's condition from the text and photos.
4. Estimate what it would cost the seller to ship this item to an eBay buyer, in USD.
5. List red flags: damage, missing parts or batteries/chargers, carrier- or iCloud-locked devices, \
signs of stolen goods, scam signs (price absurdly low, shipping-only, off-platform payment), or \
anything else that would lower resale value.

Set confidence to high only when the product is unambiguous and at least 3 eBay listings clearly match; \
low when the product, configuration or condition is uncertain."""


def triage(client: anthropic.Anthropic, listings: list[Listing], categories: list[str]) -> dict[str, TriageItem]:
    """Cheap first pass over titles and prices. Returns verdicts keyed by listing id."""
    verdicts: dict[str, TriageItem] = {}
    system = TRIAGE_SYSTEM.format(categories=", ".join(categories))
    for start in range(0, len(listings), TRIAGE_BATCH):
        batch = listings[start : start + TRIAGE_BATCH]
        payload = [{"id": l.id, "title": l.title, "price": l.price, "location": l.location} for l in batch]
        resp = client.messages.parse(
            model=TRIAGE_MODEL,
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": json.dumps(payload, indent=1)}],
            output_format=TriageResult,
            output_config={"effort": "low"},
        )
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            log.warning("triage returned no result (stop_reason=%s)", resp.stop_reason)
            continue
        ids = {l.id for l in batch}
        verdicts.update({v.id: v for v in resp.parsed_output.items if v.id in ids})
    return verdicts


def value(
    client: anthropic.Anthropic,
    listing: Listing,
    product_hint: str,
    comps: list[Comp],
    photos: list[tuple[bytes, str]],
) -> Valuation | None:
    """Detailed valuation of one listing against its eBay comps, using its photos."""
    content: list[dict] = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(data).decode()},
        }
        for data, media_type in photos
    ]
    comp_lines = "\n".join(
        f"{i}. ${c.price:.2f} + ${c.shipping:.2f} shipping | {c.condition or 'condition n/a'} | {c.title}"
        for i, c in enumerate(comps, 1)
    )
    content.append(
        {
            "type": "text",
            "text": (
                f"Marketplace listing\nTitle: {listing.title}\nAsking price: ${listing.price:.2f}\n"
                f"Location: {listing.location}\nLikely product: {product_hint}\n\n"
                f"Page text:\n{listing.page_text or '(not available)'}\n\n"
                f"eBay listings:\n{comp_lines}"
            ),
        }
    )
    resp = client.beta.messages.parse(
        model=VALUATION_MODEL,
        max_tokens=16000,
        system=VALUATION_SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_format=Valuation,
        output_config={"effort": "medium"},
        # On a safety-classifier decline, retry server-side on Anthropic's recommended fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        log.warning("valuation returned no result for %s (stop_reason=%s)", listing.id, resp.stop_reason)
        return None
    return resp.parsed_output


def compute_deal(listing: Listing, valuation: Valuation, comps: list[Comp], t: ThresholdConfig) -> Deal:
    matched = [comps[i - 1] for i in dict.fromkeys(valuation.matching_comps) if 1 <= i <= len(comps)]
    resale = statistics.median(c.total for c in matched) * t.active_to_sold_ratio if matched else 0.0
    net = resale * (1 - t.ebay_fee_rate) - valuation.shipping_estimate
    profit = net - listing.price
    margin = profit / listing.price if listing.price > 0 else None
    return Deal(
        listing=listing,
        valuation=valuation,
        comps=matched,
        resale=round(resale, 2),
        net=round(net, 2),
        profit=round(profit, 2),
        margin=margin,
    )


def should_alert(deal: Deal, t: ThresholdConfig) -> bool:
    return (
        len(deal.comps) >= t.min_comps
        and deal.profit >= t.min_profit
        and (deal.margin is None or deal.margin >= t.min_margin)
        and CONFIDENCE_RANK[deal.valuation.confidence] >= CONFIDENCE_RANK[t.min_confidence]
        and deal.valuation.condition != "for_parts"
    )
