import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

import httpx2 as httpx

from bot import config

log = logging.getLogger(__name__)

API_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"

FIRST_HALF = "STATUS_FIRST_HALF"
HALFTIME = "STATUS_HALFTIME"
SCHEDULED = "STATUS_SCHEDULED"


@dataclass
class Goal:
    minute: str
    player: str
    side: str
    own_goal: bool = False
    penalty: bool = False


@dataclass
class Match:
    id: str
    slug: str
    tag: str
    competition: str
    kickoff: str
    url: str
    home: str
    away: str
    home_score: int
    away_score: int
    home_pens: int | None = None
    away_pens: int | None = None
    goals: list[Goal] = field(default_factory=list)
    red_cards: list[Goal] = field(default_factory=list)
    state: str = ""
    completed: bool = False
    minute: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Match":
        d = dict(d)
        d["goals"] = [Goal(**g) for g in d.get("goals", [])]
        d["red_cards"] = [Goal(**g) for g in d.get("red_cards", [])]
        return cls(**d)

    @property
    def kickoff_at(self) -> datetime | None:
        return datetime.fromisoformat(self.kickoff.replace("Z", "+00:00")) if self.kickoff else None

    @property
    def event(self) -> str:
        return f"{self.home} {self.home_score}-{self.away_score} {self.away} match result"


def _parse(event: dict, slug: str, tag: str, competition: str) -> Match | None:
    comp = event["competitions"][0]
    status = event.get("status", {})
    sides = {c["homeAway"]: c for c in comp["competitors"]}
    home, away = sides.get("home"), sides.get("away")
    if not home or not away:
        return None
    ids = {int(home["team"]["id"]), int(away["team"]["id"])}
    if not ids & set(config.TOP_TEAMS):
        return None

    side_by_team = {home["team"]["id"]: "home", away["team"]["id"]: "away"}
    goals, reds = [], []
    for d in comp.get("details", []):
        if d.get("shootout"):
            continue
        players = [a.get("displayName", "") for a in d.get("athletesInvolved", [])]
        entry = Goal(
            minute=d.get("clock", {}).get("displayValue", "").strip(),
            player=players[0] if players else "",
            side=side_by_team.get(d.get("team", {}).get("id"), "home"),
            own_goal=bool(d.get("ownGoal")),
            penalty=bool(d.get("penaltyKick")),
        )
        if d.get("scoringPlay"):
            goals.append(entry)
        elif d.get("redCard"):
            reds.append(entry)

    link = next((l["href"] for l in event.get("links", []) if "href" in l), "")
    return Match(
        id=event["id"], slug=slug, tag=tag, competition=competition,
        kickoff=event.get("date", ""), url=link,
        home=home["team"]["displayName"], away=away["team"]["displayName"],
        home_score=int(home.get("score") or 0), away_score=int(away.get("score") or 0),
        home_pens=home.get("shootoutScore"), away_pens=away.get("shootoutScore"),
        goals=goals, red_cards=reds,
        state=status.get("type", {}).get("name", ""),
        completed=bool(status.get("type", {}).get("completed")),
        minute=int((status.get("clock") or 0) // 60),
    )


def fetch_matches(days: list[str], competitions: list[tuple[str, str, str]] | None = None
                  ) -> tuple[list[Match], list[str]]:
    matches: dict[str, Match] = {}
    errors = []
    with httpx.Client(timeout=config.HTTP_TIMEOUT) as client:
        for slug, tag, competition in (config.MATCH_COMPETITIONS if competitions is None else competitions):
            for day in days:
                try:
                    response = client.get(API_URL.format(slug=slug), params={"dates": day})
                    response.raise_for_status()
                    events = response.json().get("events", [])
                except (httpx.HTTPError, ValueError) as e:
                    errors.append(f"{slug}: {type(e).__name__}")
                    continue
                for event in events:
                    try:
                        match = _parse(event, slug, tag, competition)
                    except (KeyError, TypeError, ValueError) as e:
                        log.warning("матч %s не разобрался: %s", event.get("id"), e)
                        continue
                    if match:
                        matches[match.id] = match
    return list(matches.values()), errors


def recent_days(hours: int) -> list[str]:
    now = datetime.now(timezone.utc)
    return sorted({(now - timedelta(hours=h)).strftime("%Y%m%d") for h in range(0, hours + 24, 24)}
                  | {(now - timedelta(hours=hours)).strftime("%Y%m%d")})


def fetch_finished(max_age_hours: int = config.MATCH_MAX_AGE_HOURS,
                   competitions: list[tuple[str, str, str]] | None = None) -> tuple[list[Match], list[str]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    found, errors = fetch_matches(recent_days(max_age_hours), competitions)
    return [m for m in found if m.completed and m.kickoff_at and m.kickoff_at >= cutoff], errors
