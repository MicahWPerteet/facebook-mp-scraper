"""One scrape-evaluate-alert cycle."""

import datetime
import logging
import random
import time

import anthropic
import httpx

from . import evaluate, marketplace
from .browser import Browser
from .config import Config
from .db import DB
from .ebay import EbayClient
from .models import Comp, Deal, Listing
from .notify import Notifier
from .usage import CostTracker

log = logging.getLogger(__name__)

COMP_CACHE_SECONDS = 24 * 3600
MAX_PHOTOS = 4


class Pipeline:
    def __init__(
        self,
        config: Config,
        db: DB,
        browser: Browser,
        claude: anthropic.Anthropic,
        ebay: EbayClient | None,  # None: stop after triage (dry runs before eBay keys exist)
        notifier: Notifier,
    ):
        self.config = config
        self.db = db
        self.browser = browser
        self.claude = claude
        self.ebay = ebay
        self.notifier = notifier

    def run_cycle(self) -> list[Deal]:
        self.costs = CostTracker(sink=self.db.record_usage)
        try:
            return self._run_cycle()
        finally:  # log spend even when the cycle ends early or raises
            if self.costs.calls:
                midnight = datetime.datetime.combine(datetime.date.today(), datetime.time()).timestamp()
                log.info(
                    "Claude cost this cycle: %s; today so far: $%.4f",
                    self.costs.summary(), self.db.cost_since(midnight),
                )

    def _run_cycle(self) -> list[Deal]:
        listings = self._search()
        if not listings:
            log.info("no new listings this cycle")
            return []

        verdicts = evaluate.triage(
            self.claude, listings, self.config.categories, self.config.thresholds.min_profit, self.costs
        )
        candidates = []
        for listing in listings:
            verdict = verdicts.get(listing.id)
            if verdict and verdict.keep:
                candidates.append((listing, verdict))
            elif verdict:
                self.db.mark(listing, "rejected")
            # No verdict (e.g. a failed triage call): leave unseen so the next cycle retries it.
        log.info("%d new listings, %d passed triage", len(listings), len(candidates))
        if self.ebay is None:
            for listing, verdict in candidates:
                self.notifier.send_text(
                    f"would evaluate: ${listing.price:.0f} {listing.title!r} -> {verdict.product}"
                    f" (eBay query {verdict.ebay_query!r}) {listing.url}"
                )
            return []

        # Anything past the per-cycle cap stays unseen and gets picked up next cycle.
        deals = []
        for listing, verdict in candidates[: self.config.schedule.max_details_per_cycle]:
            try:
                deal = self._evaluate(listing, verdict.product, verdict.ebay_query)
            except (anthropic.APIError, httpx.HTTPError) as e:  # Blocked is neither, so it propagates
                log.warning("evaluating %s failed: %s", listing.id, e)
                self.db.mark(listing, "error")
                continue
            if deal:
                deals.append(deal)
            self.browser.pause()
        return deals

    def _search(self) -> list[Listing]:
        searches = list(self.config.searches)
        random.shuffle(searches)
        new: dict[str, Listing] = {}
        for search in searches[: self.config.schedule.max_searches_per_cycle]:
            url = marketplace.search_url(self.config.city, search, self.config.days_since_listed)
            html = self.browser.visit(url, scrolls=random.randint(2, 3))
            found = marketplace.parse_search_results(html)
            log.info("search %r: %d cards", search.query, len(found))
            if not found:
                self._save_debug(f"search-{search.query}", html)
            for listing in found:
                if listing.id not in new and not self.db.is_seen(listing.id):
                    new[listing.id] = listing
            self.browser.pause()
        return list(new.values())

    def _evaluate(self, listing: Listing, product: str, query: str) -> Deal | None:
        html = self.browser.visit(listing.url, scrolls=1)
        listing.page_text, listing.photo_urls = marketplace.parse_detail(html)
        photos = [p for u in listing.photo_urls[:MAX_PHOTOS] if (p := self.browser.fetch_image(u))]

        comps = self._comps(query)
        if not comps:
            log.info("%s: no eBay comps for %r", listing.id, query)
            self.db.mark(listing, "no_comps")
            return None

        valuation = evaluate.value(self.claude, listing, product, comps, photos, self.costs)
        if valuation is None:
            self.db.mark(listing, "error")
            return None

        t = self.config.thresholds
        deal = evaluate.compute_deal(listing, valuation, comps, t)
        alert = evaluate.should_alert(deal, t)
        log.info(
            "%s: %s | ask $%.0f resale $%.0f profit $%.0f %s%s",
            listing.id, valuation.product, listing.price, deal.resale, deal.profit,
            valuation.confidence, " -> ALERT" if alert else "",
        )
        if alert:
            self.notifier.send_deal(deal)
        self.db.save_deal(deal, alerted=alert)
        return deal if alert else None

    def _comps(self, query: str) -> list[Comp]:
        cached = self.db.cached_comps(query, COMP_CACHE_SECONDS)
        if cached is not None:
            return cached
        comps = self.ebay.search(query)
        self.db.cache_comps(query, comps)
        return comps

    def _save_debug(self, name: str, html: str) -> None:
        self.config.debug_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() else "-" for ch in name)[:60]
        path = self.config.debug_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}.html"
        path.write_text(html)
        log.info("saved page HTML to %s for parser debugging", path)
