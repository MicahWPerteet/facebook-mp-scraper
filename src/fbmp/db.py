import json
import sqlite3
import time
from pathlib import Path

from .models import Comp, Deal, Listing
from .usage import Usage

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    price REAL NOT NULL,
    status TEXT NOT NULL,  -- rejected | no_comps | error | evaluated | alerted
    first_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluations (
    listing_id TEXT PRIMARY KEY REFERENCES listings(id),
    deal TEXT NOT NULL,  -- Deal as JSON
    profit REAL NOT NULL,
    alerted INTEGER NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS claude_usage (
    ts REAL NOT NULL,
    step TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost REAL  -- NULL when the model has no known price
);
CREATE TABLE IF NOT EXISTS comp_cache (
    query TEXT PRIMARY KEY,
    comps TEXT NOT NULL,  -- list[Comp] as JSON
    fetched REAL NOT NULL
);
"""


class DB:
    def __init__(self, path: Path | str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)

    def is_seen(self, listing_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,)).fetchone()
        return row is not None

    def mark(self, listing: Listing, status: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO listings (id, title, price, status, first_seen) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET status = excluded.status",
                (listing.id, listing.title, listing.price, status, time.time()),
            )

    def save_deal(self, deal: Deal, alerted: bool) -> None:
        self.mark(deal.listing, "alerted" if alerted else "evaluated")
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO evaluations (listing_id, deal, profit, alerted, created)"
                " VALUES (?, ?, ?, ?, ?)",
                (deal.listing.id, deal.model_dump_json(), deal.profit, int(alerted), time.time()),
            )

    def record_usage(self, usage: Usage) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO claude_usage (ts, step, model, input_tokens, output_tokens, cost)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), usage.step, usage.model, usage.input_tokens, usage.output_tokens, usage.cost),
            )

    def cost_since(self, ts: float) -> float:
        row = self.conn.execute("SELECT COALESCE(SUM(cost), 0) FROM claude_usage WHERE ts >= ?", (ts,)).fetchone()
        return row[0]

    def cached_comps(self, query: str, max_age_seconds: float) -> list[Comp] | None:
        row = self.conn.execute(
            "SELECT comps, fetched FROM comp_cache WHERE query = ?", (query.lower(),)
        ).fetchone()
        if row is None or time.time() - row[1] > max_age_seconds:
            return None
        return [Comp.model_validate(c) for c in json.loads(row[0])]

    def cache_comps(self, query: str, comps: list[Comp]) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO comp_cache (query, comps, fetched) VALUES (?, ?, ?)",
                (query.lower(), json.dumps([c.model_dump() for c in comps]), time.time()),
            )
