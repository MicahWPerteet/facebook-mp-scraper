import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

from .models import Confidence


class SearchConfig(BaseModel):
    query: str
    min_price: int | None = None
    max_price: int | None = None


class ScheduleConfig(BaseModel):
    interval_minutes: tuple[float, float] = (30, 60)
    quiet_start_hour: int = 23  # no activity from this hour...
    quiet_end_hour: int = 8  # ...until this hour (local time)
    max_searches_per_cycle: int = 6
    max_details_per_cycle: int = 10
    action_delay_seconds: tuple[float, float] = (4, 12)


class ThresholdConfig(BaseModel):
    min_profit: float = 75
    min_margin: float = 0.40
    min_confidence: Confidence = "medium"
    min_comps: int = 3
    ebay_fee_rate: float = 0.136
    # eBay's Browse API only returns active listings; sold prices usually run lower.
    active_to_sold_ratio: float = 0.85


class Config(BaseModel):
    city: str  # the slug in facebook.com/marketplace/<city>/
    days_since_listed: int = 1
    categories: list[str] = Field(default_factory=lambda: ["electronics", "tools & equipment"])
    searches: list[SearchConfig]
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    thresholds: ThresholdConfig = Field(default_factory=ThresholdConfig)
    data_dir: Path = Path("data")

    @property
    def profile_dir(self) -> Path:
        return self.data_dir / "profile"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "fbmp.sqlite3"

    @property
    def debug_dir(self) -> Path:
        return self.data_dir / "debug"


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        return Config.model_validate(tomllib.load(f))


def load_env(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE lines into os.environ without overriding variables already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set. Add it to .env (see .env.example).")
    return value
