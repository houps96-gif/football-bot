import re
import unicodedata

from bot import config
from bot.llm import LLM
from bot.llm.base import TRIAGE_SCHEMA
from bot.models import NewsItem

SYSTEM = config.TRIAGE_SYSTEM


def _system() -> str:
    favorite = ""
    if config.FAVORITE_CLUB and config.FAVORITE_BOOST:
        favorite = (f"«{config.FAVORITE_CLUB}» — любимый клуб канала, его читатели хотят знать о клубе всё. "
                    f"Любую новость, где «{config.FAVORITE_CLUB}» — главное действующее лицо, оценивай "
                    f"на {config.FAVORITE_BOOST} балла выше, чем такую же новость о другом клубе (но не выше 10): "
                    "слухи о трансферах, травмы, интервью игроков и тренера, академия тоже интересны. "
                    f"Женская команда «{config.FAVORITE_CLUB}» — исключение из правила про женский футбол: relevant = true.")
    return SYSTEM.replace("{favorite}", favorite)


def clean_topic(value) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def triage(llm: LLM, items: list[NewsItem], recent: list[dict]) -> dict[str, dict]:
    parts = []
    if recent:
        lines = [f"- {r['topic']} | {r['event']}" if r.get("topic") else f"- {r['event']}" for r in recent[-80:]]
        parts.append("Уже в канале (за последние 48 часов):\n" + "\n".join(lines))
    parts.append("Новости:\n" + "\n".join(f"{it.id} | {it.source} | {it.title} | {it.summary[:200]}" for it in items))
    result = llm.generate_json(_system(), "\n\n".join(parts), TRIAGE_SCHEMA, max_tokens=8192)

    known = {it.id for it in items}
    out = {}
    for row in result.get("items", []):
        if row.get("id") not in known:
            continue
        try:
            importance = int(row.get("importance", 0))
        except (TypeError, ValueError):
            continue
        out[row["id"]] = {
            "relevant": bool(row.get("relevant")),
            "importance": max(1, min(10, importance)),
            "league": row.get("league") if row.get("league") in config.LEAGUES else "Другое",
            "event": str(row.get("event", "")).strip(),
            "topic": clean_topic(row.get("topic")),
            "duplicate": bool(row.get("duplicate")),
        }
    return out
