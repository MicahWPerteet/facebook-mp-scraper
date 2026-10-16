import html
import logging
from typing import Protocol

import httpx

from .models import Deal

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024  # Telegram's limit for photo captions


class Notifier(Protocol):
    def send_deal(self, deal: Deal) -> None: ...
    def send_text(self, text: str) -> None: ...


def format_deal(deal: Deal, limit: int = CAPTION_LIMIT) -> str:
    """Telegram-HTML message for a deal, trimmed to fit `limit` characters."""
    l, v = deal.listing, deal.valuation
    margin = "free item" if deal.margin is None else f"{deal.margin:.0%} margin"
    head = [
        f"<b>💰 ${deal.profit:.0f} profit</b> ({margin}, {v.confidence} confidence)",
        f"<b>{html.escape(v.product)}</b>",
        f"Asking ${l.price:.0f} · eBay ~${deal.resale:.0f} · net ${deal.net:.0f} after fees/shipping",
        f"Condition: {v.condition.replace('_', ' ')} · {html.escape(l.location)}",
        f'<a href="{html.escape(l.url)}">Open listing</a>',
    ]
    tail = [html.escape(v.summary)]
    if v.red_flags:
        tail.append("⚠️ " + html.escape("; ".join(v.red_flags)))
    comps = [
        f'• <a href="{html.escape(c.url)}">${c.total:.0f}</a> {html.escape(c.title[:60])}' for c in deal.comps[:3]
    ]
    text = "\n".join(head + [""] + tail + ([""] + comps if comps else []))
    if len(text) > limit:  # drop optional sections rather than cut through an HTML tag
        text = "\n".join(head + [""] + tail)
    if len(text) > limit:
        text = "\n".join(head)
    return text


class ConsoleNotifier:
    def send_deal(self, deal: Deal) -> None:
        print("\n" + format_deal(deal, limit=10_000) + "\n")

    def send_text(self, text: str) -> None:
        print(text)


class TelegramError(RuntimeError):
    pass


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, http: httpx.Client | None = None):
        self._base = f"https://api.telegram.org/bot{token}"
        self.chat_id = chat_id
        self._http = http or httpx.Client(timeout=20)

    def _call(self, method: str, **payload) -> dict:
        r = self._http.post(f"{self._base}/{method}", json=payload)
        body = r.json()
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', r.status_code)}")
        return body["result"]

    def send_text(self, text: str) -> None:
        self._call("sendMessage", chat_id=self.chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)

    def send_deal(self, deal: Deal) -> None:
        caption = format_deal(deal)
        if deal.listing.image_url:
            try:
                self._call(
                    "sendPhoto", chat_id=self.chat_id, photo=deal.listing.image_url, caption=caption, parse_mode="HTML"
                )
                return
            except TelegramError as e:  # Telegram couldn't fetch the Facebook CDN image
                log.info("sendPhoto failed, sending text instead: %s", e)
        self.send_text(caption)

    def chats(self) -> list[tuple[str, str]]:
        """(chat id, name) for everyone who has messaged the bot recently."""
        found: dict[str, str] = {}
        for update in self._call("getUpdates"):
            msg = update.get("message") or update.get("channel_post") or {}
            chat = msg.get("chat")
            if chat:
                name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
                found[str(chat["id"])] = name or chat.get("username", "")
        return list(found.items())
