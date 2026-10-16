# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                   # install deps (Python ≥3.12, uv-managed)
uv run pytest                             # all tests (offline, no browser or API calls)
uv run pytest tests/test_profit.py::test_should_alert -q   # single test
uv run fbmp login                         # open the persistent Chrome profile to log in by hand
uv run fbmp run --once --dry-run          # one live cycle; prints deals, uses an in-memory DB
uv run fbmp run                           # continuous loop with Telegram alerts
uv run fbmp test-notify | telegram-setup  # Telegram checks
```

Runtime config lives in `config.toml` (from `config.example.toml`) and secrets in `.env` (from `.env.example`). Both are gitignored, as is `data/`, which holds the browser profile, the SQLite DB and debug HTML dumps.

## Architecture

`cli.py` runs a loop, and `pipeline.Pipeline.run_cycle()` makes one pass:

1. **Search** (`marketplace.search_url`, then `Browser.visit`, then `parse_search_results`): runs the configured searches in random order. Listing IDs already in SQLite are skipped.
2. **Triage** (`evaluate.triage`, Claude Haiku 5.5): one batched structured-output call over titles and prices. It returns keep/reject, a product name and an eBay query.
3. **Detail** (`parse_detail`): opens the detail page for kept listings only, up to `max_details_per_cycle`. Photos are downloaded through the browser context because the Facebook CDN needs its cookies.
4. **Comps** (`ebay.EbayClient`): Browse API search, cached for 24 hours in SQLite per query.
5. **Valuation** (`evaluate.value`, Claude Sonnet 5.5 with photos): picks the matching comps by number and returns condition, shipping estimate, confidence and red flags. It uses `beta.messages.parse` with `fallbacks="default"` for refusal fallback.
6. **Profit** (`evaluate.compute_deal` / `should_alert`): plain-code math, no Claude. Then `notify.TelegramNotifier`.

The non-obvious constraints:

- **eBay blocks automated browsers.** `curl`, headless Chrome and Playwright-driven headed Chrome all got a 403 or CAPTCHA, so comps come from the official Browse API. That API returns *active* listings only (sold data needs the restricted Marketplace Insights API), so prices are discounted by `active_to_sold_ratio`.
- **The account-safety design is intentional; don't "improve" it.** The browser is headed, persistent and Chrome-channel, with randomized pauses. There is no stealth, proxying or CAPTCHA solving. `browser.detect_block` raises `Blocked`, which ends the run (exit code 2) after a Telegram notice. Pipeline error handling catches only `anthropic.APIError` and `httpx.HTTPError` per listing, so `Blocked` always propagates.
- **Facebook markup is obfuscated.** Parsers rely only on `a[href*="/marketplace/item/<id>"]`, the text order inside a card (price, optional old price, title, location) and `[role="main"]`. When a search yields zero cards, the page HTML is saved to `data/debug/`. Start from there when the parser breaks, and refresh `tests/fixtures/` from a real capture. The current fixtures are hand-built.
- **Listing status lifecycle** (`db.py`): `rejected`, `no_comps`, `error`, `evaluated` or `alerted`. Listings with no triage verdict, or past the per-cycle detail cap, are deliberately left unmarked so the next cycle retries them.
- **Claude output models** (`TriageResult`, `Valuation` in `models.py`) are passed as `output_format=` to `messages.parse`. Field descriptions there are part of the prompt.
- The `httpx` logger is forced to WARNING because Telegram's bot token is part of the request URL.
