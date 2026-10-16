# fbmp — Facebook Marketplace flip finder

Watches Facebook Marketplace for electronics and tools listed below their resale value. It asks Claude to identify each promising item, compares the asking price against eBay listings, and sends a Telegram alert when the estimated profit clears your thresholds.

## How it avoids getting your account banned

Scraping Marketplace breaks Meta's Terms of Service, and there is always some risk to the account you use. This tool keeps that risk low by acting like a person browsing, not by hiding that it's automated:

- It runs a **visible** Chrome window with its own profile that you log into by hand. No credentials are stored.
- It loads only a few searches per cycle, waits 4–12 seconds between page actions, waits 30–60 minutes between cycles, and stays idle overnight.
- It opens a listing's detail page only after Claude's first pass says the listing is worth a look.
- It **stops immediately** if it sees a login wall, checkpoint, CAPTCHA or "temporarily blocked" page, and sends you a Telegram message about it. It never retries on its own.

It does not spoof browser fingerprints, rotate proxies or solve CAPTCHAs. Those tricks raise the stakes if Facebook notices.

## Setup

```bash
uv sync
cp config.example.toml config.toml   # set your city and searches
cp .env.example .env                 # fill in the keys below
```

You'll need these keys:

- **Anthropic**: an API key from console.anthropic.com.
- **Telegram**:
  1. Message @BotFather, run `/newbot`, and put the token in `TELEGRAM_BOT_TOKEN`.
  2. Send your new bot any message.
  3. Run `uv run fbmp telegram-setup` and copy your chat ID into `TELEGRAM_CHAT_ID`.
- **eBay**: at developer.ebay.com, create an application and copy its **Production** keyset into `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET`. eBay asks about marketplace account deletion notifications before it enables the keys. This tool stores no eBay user data, so you can apply for the exemption.

Then log in once:

```bash
uv run fbmp login   # log in to Facebook in the window, set your Marketplace location, press Enter
```

## Usage

```bash
uv run fbmp test-notify            # sample alert to Telegram
uv run fbmp run --once --dry-run   # one cycle, print deals, store nothing
uv run fbmp run                    # keep running and send alerts
```

## How the profit estimate works

eBay's public API only returns **active** listings, not sold ones, so the tool estimates the resale price in four steps:

1. It takes the median price plus shipping of the eBay listings that Claude says match the item.
2. It multiplies that by `active_to_sold_ratio` (default 0.85), because sold prices usually run below asking prices.
3. It subtracts eBay fees and Claude's shipping estimate.
4. It subtracts the Marketplace asking price. The result is the profit figure in the alert.

All of these thresholds can be changed in `config.toml`.
