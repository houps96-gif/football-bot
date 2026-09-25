import html
import logging
from datetime import datetime, timedelta, timezone

from bot import config, results
from bot.llm import LLMError, get_llm
from bot.sources.matches import FIRST_HALF, HALFTIME, Match, fetch_matches, recent_days
from bot.store import Store, age_hours, ts
from bot.telegram import Telegram, TelegramError

log = logging.getLogger(__name__)

CHECK_SECONDS = 120
IDLE_SECONDS = 600
FIXTURES_REFRESH_HOURS = 0.5
NEAR_BEFORE = timedelta(minutes=10)
NEAR_AFTER = timedelta(hours=3)
START_MAX_MINUTE = 30


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def refresh_fixtures(st: Store) -> list[Match]:
    cache = st.data.setdefault("fixtures", {})
    if not cache.get("at") or age_hours(cache["at"]) >= FIXTURES_REFRESH_HOURS:
        found, _ = fetch_matches(recent_days(24))
        cache.update(at=ts(), matches=[m.to_dict() for m in found])
        log.info("расписание: матчей команд из списка за сутки: %d", len(found))
    return [Match.from_dict(m) for m in cache.get("matches", [])]


def _save_fixtures(st: Store, matches: list[Match]) -> None:
    st.data["fixtures"]["matches"] = [m.to_dict() for m in matches]


def _near(matches: list[Match]) -> list[Match]:
    now = datetime.now(timezone.utc)
    return [m for m in matches if not m.completed and m.kickoff_at
            and m.kickoff_at - NEAR_BEFORE <= now <= m.kickoff_at + NEAR_AFTER]


def result_competitions(st: Store) -> list[tuple[str, str, str]] | None:
    cache = st.data.get("fixtures", {})
    if not cache.get("at") or age_hours(cache["at"]) >= 1:
        return None
    now = datetime.now(timezone.utc)
    window = timedelta(hours=config.MATCH_MAX_AGE_HOURS)
    slugs = {m.slug for m in map(Match.from_dict, cache.get("matches", []))
             if m.kickoff_at and now - window <= m.kickoff_at <= now}
    return [c for c in config.MATCH_COMPETITIONS if c[0] in slugs]


def next_delay(st: Store) -> int:
    return CHECK_SECONDS if _near(refresh_fixtures(st)) else IDLE_SECONDS


class Live:
    def __init__(self, tg: Telegram):
        self.tg = tg
        self._llm = None


    def _names(self, st: Store, m: Match, players: bool) -> dict[str, str]:
        cache = st.data["names_ru"]
        names = results.match_names([m], players=players)
        if not results.missing_names(names, cache):
            return results.lookup(names, cache)
        if st.daily["llm_calls"] + st.daily["llm_errors"] >= config.LLM_MAX_CALLS_PER_DAY:
            return results.lookup(names, cache)
        try:
            self._llm = self._llm or get_llm()
            st.bump("llm_calls")
            return results.translate(self._llm, names, cache)
        except LLMError as e:
            st.bump("llm_errors")
            log.warning("живой режим: имена не перевелись: %s", e)
            return results.lookup(names, cache)


    def _start_text(self, m: Match, ru: dict[str, str]) -> str:
        home, away = ru.get(m.home, m.home), ru.get(m.away, m.away)
        return f"<b>{_esc(home)} — {_esc(away)}</b>\n{_esc(m.competition)} · матч начался"

    def _half_text(self, m: Match, ru: dict[str, str]) -> str:
        home, away = ru.get(m.home, m.home), ru.get(m.away, m.away)
        lines = [f"<b>{_esc(home)} — {_esc(away)} {m.home_score}:{m.away_score}</b>",
                 f"{_esc(m.competition)} · перерыв"]
        goals = results.goal_lines(m, ru)
        if goals and goals != ["Без голов."]:
            lines += [""] + goals
        return "\n".join(lines)


    def check(self, st: Store) -> bool:
        live = st.data["live"]
        for match_id, entry in list(live.items()):
            if match_id in st.data["matches_posted"] or age_hours(entry["ts"]) > 6:
                try:
                    self.tg.delete_message(config.CHANNEL_ID, entry["message_id"])
                except TelegramError as e:
                    log.info("живой пост не удалился: %s", e)
                del live[match_id]

        fixtures = refresh_fixtures(st)
        near = _near(fixtures)
        if not near:
            return False

        slugs = {m.slug for m in near}
        competitions = [c for c in config.MATCH_COMPETITIONS if c[0] in slugs]
        days = sorted({m.kickoff_at.strftime("%Y%m%d") for m in near})
        fresh = {m.id: m for m in fetch_matches(days, competitions)[0]}

        finished = False
        for old in near:
            m = fresh.get(old.id)
            if not m:
                continue
            entry = live.get(m.id)
            if m.completed:
                finished = finished or m.id not in st.data["matches_posted"]
            elif m.state == HALFTIME and (not entry or entry["stage"] == "start"):
                self._post(st, m, "half", self._half_text(m, self._names(st, m, players=True)), entry)
            elif m.state == FIRST_HALF and not entry and m.minute <= START_MAX_MINUTE:
                self._post(st, m, "start", self._start_text(m, self._names(st, m, players=False)), None)

        _save_fixtures(st, [fresh.get(m.id, m) for m in fixtures])
        return finished

    def _post(self, st: Store, m: Match, stage: str, text: str, entry: dict | None) -> None:
        if entry:
            try:
                self.tg.edit_message_text(config.CHANNEL_ID, entry["message_id"], text)
                entry.update(stage=stage, ts=ts())
                log.info("живой пост %s: %s — %s", stage, m.home, m.away)
                return
            except TelegramError as e:
                log.info("живой пост не отредактировался (%s), публикую новый", e)
        message = self.tg.send_message(config.CHANNEL_ID, text, silent=True)
        st.data["live"][m.id] = {"message_id": message["message_id"], "stage": stage, "ts": ts()}
        log.info("живой пост %s: %s — %s", stage, m.home, m.away)
