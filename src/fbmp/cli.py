import argparse
import datetime as dt
import logging
import os
import random
import sys
import time
from pathlib import Path

import anthropic

from .browser import Blocked, Browser
from .config import Config, ScheduleConfig, ThresholdConfig, load_config, load_env, require_env
from .db import DB
from .ebay import EbayClient
from .evaluate import compute_deal
from .models import Comp, Deal, Listing, Valuation
from .notify import ConsoleNotifier, TelegramNotifier
from .pipeline import Pipeline

log = logging.getLogger("fbmp")


def in_quiet_hours(hour: int, s: ScheduleConfig) -> bool:
    start, end = s.quiet_start_hour, s.quiet_end_hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # window wraps past midnight


def seconds_until_hour(now: dt.datetime, hour: int) -> float:
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


def _telegram():
    return TelegramNotifier(require_env("TELEGRAM_BOT_TOKEN"), require_env("TELEGRAM_CHAT_ID"))


def cmd_login(config: Config, args) -> int:
    with Browser(config.profile_dir) as b:
        b.page.goto("https://www.facebook.com/marketplace/")
        print(
            "A Chrome window is open with the scraper's profile.\n"
            "Log in to Facebook there by hand (and finish any security check),\n"
            "then set your Marketplace location and radius on the Marketplace page.\n"
            "Close the Chrome window when you're done; the session is saved automatically.",
            flush=True,
        )
        # Wait for the window rather than stdin, which isn't interactive in every shell.
        b.context.wait_for_event("close", timeout=0)
    print("Session saved.")
    return 0


def cmd_run(config: Config, args) -> int:
    require_env("ANTHROPIC_API_KEY")
    if args.dry_run and not (os.environ.get("EBAY_CLIENT_ID") and os.environ.get("EBAY_CLIENT_SECRET")):
        log.warning("no eBay keys: dry run will stop after triage")
        ebay = None
    else:
        ebay = EbayClient(require_env("EBAY_CLIENT_ID"), require_env("EBAY_CLIENT_SECRET"))
    notifier = ConsoleNotifier() if args.dry_run else _telegram()
    # A dry run gets a throwaway database so it doesn't mark listings as already seen.
    db = DB(":memory:" if args.dry_run else config.db_path)
    s = config.schedule

    with Browser(config.profile_dir, s.action_delay_seconds) as browser:
        pipeline = Pipeline(config, db, browser, anthropic.Anthropic(), ebay, notifier)
        while True:
            now = dt.datetime.now()
            if not args.once and in_quiet_hours(now.hour, s):
                wait = seconds_until_hour(now, s.quiet_end_hour) + random.uniform(0, 1800)
                log.info("quiet hours; sleeping %.1f h", wait / 3600)
                time.sleep(wait)
                continue
            try:
                deals = pipeline.run_cycle()
                log.info("cycle done: %d alert(s)", len(deals))
            except Blocked as e:
                log.error("Facebook blocked the session: %s", e)
                notifier.send_text(
                    f"⚠️ <b>fbmp stopped</b>: Facebook showed {e}.\n"
                    "Run <code>fbmp login</code>, resolve it by hand, and give it a day before restarting."
                )
                return 2
            except Exception:
                if args.once:
                    raise
                log.exception("cycle failed; will try again next cycle")
            if args.once:
                return 0
            wait = random.uniform(*s.interval_minutes) * 60
            log.info("next cycle in %.0f min", wait / 60)
            time.sleep(wait)


def sample_deal() -> Deal:
    listing = Listing(id="0", title="DeWalt 20V drill + 2 batteries", price=60, location="Test, WA")
    comps = [
        Comp(title="DeWalt DCD791D2 20V Max XR Drill Kit", price=p, shipping=12, url="https://www.ebay.com/")
        for p in (165, 172, 180)
    ]
    valuation = Valuation(
        product="DeWalt DCD791D2 20V drill kit",
        matching_comps=[1, 2, 3],
        condition="good",
        shipping_estimate=14,
        confidence="high",
        red_flags=[],
        summary="This is a test alert from fbmp.",
    )
    return compute_deal(listing, valuation, comps, ThresholdConfig())


def cmd_test_notify(config: Config, args) -> int:
    _telegram().send_deal(sample_deal())
    print("Sent a sample alert to Telegram.")
    return 0


def cmd_telegram_setup(config: Config, args) -> int:
    chats = TelegramNotifier(require_env("TELEGRAM_BOT_TOKEN"), "").chats()
    if not chats:
        print("No messages found. Send your bot any message in Telegram, then run this again.")
        return 1
    for chat_id, name in chats:
        print(f"{chat_id}\t{name}")
    print("\nPut your chat id in .env as TELEGRAM_CHAT_ID=<id>.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fbmp", description="Facebook Marketplace flip finder")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="open the browser profile so you can log in to Facebook by hand")
    run = sub.add_parser("run", help="watch Marketplace and send alerts")
    run.add_argument("--once", action="store_true", help="run a single cycle, ignoring quiet hours")
    run.add_argument("--dry-run", action="store_true", help="print deals instead of sending, don't persist")
    sub.add_parser("test-notify", help="send a sample alert to Telegram")
    sub.add_parser("telegram-setup", help="print chat ids that have messaged your bot")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs full request URLs, and the Telegram bot token is part of the URL.
    # httpx2 (used by the anthropic SDK) just adds a line per request.
    for name in ("httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    load_env()

    if args.command in ("telegram-setup", "test-notify"):
        config = None
    elif not args.config.exists():
        sys.exit(f"{args.config} not found. Copy config.example.toml to config.toml and edit it.")
    else:
        config = load_config(args.config)

    handlers = {
        "login": cmd_login,
        "run": cmd_run,
        "test-notify": cmd_test_notify,
        "telegram-setup": cmd_telegram_setup,
    }
    return handlers[args.command](config, args)


if __name__ == "__main__":
    sys.exit(main())
