import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from bot import config, results
from bot.llm import LLMError, get_llm
from bot.sources.matches import HALFTIME, SCHEDULED, Match, fetch_matches
from bot.store import Store
from bot.telegram import Telegram, TelegramError

log = logging.getLogger(__name__)

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]
POSTPONED = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED", "STATUS_SUSPENDED"}


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _local_now() -> datetime:
    return datetime.now(ZoneInfo(config.NIGHT_TZ))


def _utc_days(local_day: datetime) -> list[str]:
    start = local_day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = local_day.replace(hour=23, minute=59, second=59, microsecond=0)
    return sorted({d.astimezone(ZoneInfo("UTC")).strftime("%Y%m%d") for d in (start, end)})


def todays_matches(competitions=None) -> list[Match]:
    now = _local_now()
    found, _ = fetch_matches(_utc_days(now), competitions)
    tz = ZoneInfo(config.NIGHT_TZ)
    return sorted(
        (m for m in found if m.kickoff_at and m.kickoff_at.astimezone(tz).date() == now.date()),
        key=lambda m: (m.kickoff, m.home),
    )


class Matchday:
    def __init__(self, tg: Telegram):
        self.tg = tg
        self._llm = None

    def _names(self, st: Store, matches: list[Match]) -> dict[str, str]:
        cache = st.data["names_ru"]
        names = results.match_names(matches, players=False)
        if results.missing_names(names, cache) and \
                st.daily["llm_calls"] + st.daily["llm_errors"] < config.LLM_MAX_CALLS_PER_DAY:
            try:
                self._llm = self._llm or get_llm()
                st.bump("llm_calls")
                results.translate(self._llm, names, cache)
            except LLMError as e:
                st.bump("llm_errors")
                log.warning("матчи дня: названия не перевелись: %s", e)
        return results.lookup(names, cache)

    def render(self, matches: list[Match], ru: dict[str, str]) -> str:
        tz = ZoneInfo(config.NIGHT_TZ)
        now = _local_now()
        lines = [f"<b>Матчи дня · {now.day} {MONTHS[now.month - 1]}</b>"]
        competition = None
        for m in matches:
            if m.competition != competition:
                competition = m.competition
                lines += ["", f"<b>{_esc(competition)}</b>"]
            home, away = _esc(ru.get(m.home, m.home)), _esc(ru.get(m.away, m.away))
            start = (f"{m.kickoff_at.astimezone(tz):%H:%M} "
                     f"({m.kickoff_at.astimezone(ZoneInfo('Europe/Moscow')):%H:%M} мск)")
            score = f"{m.home_score}:{m.away_score}"
            if m.state in POSTPONED:
                lines.append(f"{start}  {home} — {away} · перенесён")
            elif m.completed:
                pens = f" (пен. {m.home_pens}:{m.away_pens})" if m.home_pens is not None else ""
                lines.append(f"{home} — {away} <b>{score}</b>{pens} · финал")
            elif m.state == HALFTIME:
                lines.append(f"{home} — {away} <b>{score}</b> · перерыв")
            elif m.state and m.state != SCHEDULED:
                minute = f"{m.minute}'" if m.minute else "идёт"
                lines.append(f"{home} — {away} <b>{score}</b> · {minute}")
            else:
                lines.append(f"{start}  {home} — {away}")
        lines += ["", "Время центральноевропейское. Счёт обновляется по ходу матчей."]
        return "\n".join(lines)

    def step(self, st: Store) -> None:
        now = _local_now()
        today = now.date().isoformat()
        md = st.data.setdefault("matchday", {})

        if md.get("date") and md["date"] != today:
            if md.get("message_id") and md.get("pinned"):
                try:
                    self.tg.call("unpinChatMessage", chat_id=config.CHANNEL_ID, message_id=md["message_id"])
                    log.info("матчи дня: откреплено")
                except TelegramError as e:
                    log.warning("матчи дня: не открепилось: %s", e)
            md.clear()

        if not md.get("date"):
            if now.hour < config.MATCHDAY_HOUR:
                return
            matches = todays_matches()
            md.update(date=today, message_id=None, text="", slugs=sorted({m.slug for m in matches}))
            if not matches:
                log.info("матчи дня: сегодня у команд из списка матчей нет")
                return
            text = self.render(matches, self._names(st, matches))
            message = self.tg.send_message(config.CHANNEL_ID, text, silent=True)
            md.update(message_id=message["message_id"], text=text)
            try:
                self.tg.call("pinChatMessage", chat_id=config.CHANNEL_ID,
                             message_id=message["message_id"], disable_notification=True)
                md["pinned"] = True
                try:
                    self.tg.delete_message(config.CHANNEL_ID, message["message_id"] + 1)
                except TelegramError:
                    pass
            except TelegramError as e:
                log.warning("матчи дня: не закрепилось: %s", e)
            log.info("матчи дня: опубликовано, матчей %d", len(matches))
            return

        if md.get("message_id"):
            competitions = [c for c in config.MATCH_COMPETITIONS if c[0] in md.get("slugs", [])]
            matches = todays_matches(competitions)
            if not matches:
                return
            text = self.render(matches, self._names(st, matches))
            if text != md.get("text"):
                try:
                    self.tg.edit_message_text(config.CHANNEL_ID, md["message_id"], text)
                    md["text"] = text
                except TelegramError as e:
                    log.warning("матчи дня: не обновилось: %s", e)
