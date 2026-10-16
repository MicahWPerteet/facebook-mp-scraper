"""The one real browser the scraper drives.

Account-safety rules live here: a visible, persistent Chrome profile that the user
logged into by hand, slow randomized pacing, and an immediate stop on any sign that
Facebook is suspicious. There is deliberately no stealth patching, proxying or
CAPTCHA solving.
"""

import logging
import random
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

log = logging.getLogger(__name__)

BLOCK_PHRASES = (
    "you're temporarily blocked",
    "you’re temporarily blocked",
    "we suspect automated behavior",
    "your account has been locked",
    "confirm your identity",
    "we've suspended your account",
    "we’ve suspended your account",
)


class Blocked(RuntimeError):
    """Facebook showed a login wall, checkpoint or block. Stop and let a human look."""


def detect_block(url: str, visible_text: str, has_password_field: bool) -> str | None:
    """Return why the page looks blocked, or None if it looks normal."""
    lowered_url = url.lower()
    if "/checkpoint" in lowered_url:
        return "account checkpoint"
    if "/login" in lowered_url or "login.php" in lowered_url:
        return "redirected to login"
    text = visible_text.lower()
    for phrase in BLOCK_PHRASES:
        if phrase in text:
            return f"page says {phrase!r}"
    if "captcha" in text:
        return "CAPTCHA shown"
    if has_password_field:
        return "login form shown (session expired?)"
    return None


class Browser:
    def __init__(self, profile_dir: Path, delay_seconds: tuple[float, float] = (4, 12)):
        self.profile_dir = profile_dir
        self.delay_seconds = delay_seconds
        self._pw: Playwright | None = None
        self.context: BrowserContext
        self.page: Page

    def __enter__(self) -> "Browser":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            str(self.profile_dir),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 850},
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.context.close()
        finally:
            if self._pw:
                self._pw.stop()

    def pause(self, low: float | None = None, high: float | None = None) -> None:
        lo, hi = (low, high) if low is not None and high is not None else self.delay_seconds
        self.page.wait_for_timeout(random.uniform(lo, hi) * 1000)

    def check(self) -> None:
        reason = detect_block(
            self.page.url,
            self.page.inner_text("body"),
            self.page.locator('input[name="pass"]').count() > 0,
        )
        if reason:
            raise Blocked(reason)

    def visit(self, url: str, scrolls: int = 0) -> str:
        """Open a page like a person would, scroll a bit, and return its HTML."""
        log.debug("visit %s", url)
        self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self.pause(2.5, 5)
        self.check()
        for _ in range(scrolls):
            self.page.mouse.wheel(0, random.randint(500, 1100))
            self.pause(1.5, 4)
        if scrolls:
            self.check()
        return self.page.content()

    def fetch_image(self, url: str) -> tuple[bytes, str] | None:
        """Download an image with the browser's cookies. Returns (bytes, media type)."""
        try:
            resp = self.context.request.get(url, timeout=20_000)
        except Exception as e:  # network errors here should never stop a cycle
            log.debug("image fetch failed: %s", e)
            return None
        media_type = resp.headers.get("content-type", "").split(";")[0].strip()
        if not resp.ok or media_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
            return None
        return resp.body(), media_type
