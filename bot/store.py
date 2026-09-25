import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot import config

DAILY_COUNTERS = (
    "collected", "triaged", "selected", "summarized", "cards",
    "off_topic", "below_threshold", "duplicates",
    "published", "rejected", "results", "llm_calls", "llm_errors", "expired",
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def ts(dt: datetime | None = None) -> str:
    return (dt or now()).isoformat(timespec="seconds")


def age_hours(stamp: str) -> float:
    return (now() - datetime.fromisoformat(stamp)).total_seconds() / 3600


def today() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(config.NIGHT_TZ)).date().isoformat()


def published_last_hour(data: dict) -> int:
    return sum(age_hours(stamp) < 1 for stamp in data["published"].values())


def _empty_daily() -> dict:
    return {"date": today(), **{k: 0 for k in DAILY_COUNTERS}}


class Store:
    def __init__(self, data: dict, path: Path):
        self.data = data
        self.path = path

    @classmethod
    def load(cls, path: Path = config.STATE_PATH) -> "Store":
        data = json.loads(path.read_text("utf-8")) if path.exists() else {}
        defaults = {
            "tg_offset": 0, "seen": {}, "inbox": {}, "pending": {}, "cards": {},
            "approved": [], "published": {}, "events": [], "matches_posted": {}, "match_tries": {},
            "names_ru": {}, "live": {},
            "feed_failures": {}, "disabled_feeds": [], "daily": _empty_daily(),
        }
        for key, value in defaults.items():
            data.setdefault(key, value)
        for key in DAILY_COUNTERS:
            data["daily"].setdefault(key, 0)
        return cls(data, path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.path)

    @property
    def daily(self) -> dict:
        return self.data["daily"]

    def bump(self, counter: str, n: int = 1) -> None:
        self.daily[counter] += n

    def roll_day(self) -> dict | None:
        if self.daily["date"] == today():
            return None
        finished = self.daily
        self.data["daily"] = _empty_daily()
        finished["disabled_feeds"] = list(self.data["disabled_feeds"])
        self.data["disabled_feeds"], self.data["feed_failures"] = [], {}
        return finished

    def prune(self) -> None:
        d = self.data
        d["seen"] = {k: v for k, v in d["seen"].items() if age_hours(v) < config.SEEN_TTL_DAYS * 24}
        d["published"] = {k: v for k, v in d["published"].items() if age_hours(v) < config.SEEN_TTL_DAYS * 24}
        d["matches_posted"] = {k: v for k, v in d["matches_posted"].items() if age_hours(v) < config.SEEN_TTL_DAYS * 24}
        d["match_tries"] = {k: v for k, v in d["match_tries"].items() if k not in d["matches_posted"]}
        d["events"] = [e for e in d["events"] if age_hours(e["ts"]) < config.EVENTS_TTL_HOURS]
        d["cards"] = {
            k: c for k, c in d["cards"].items()
            if c["status"] in ("sent", "approved") or age_hours(c["sent"]) < 72
        }
        d["approved"] = [i for i in d["approved"] if i in d["cards"]]
