import json
import re
import unicodedata
from functools import lru_cache

from bot import config

MAX_HITS = 40


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).replace("ø", "o").replace("Ø", "O")


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern, str]]:
    if not config.GLOSSARY_PATH.exists():
        return []
    entries = json.loads(config.GLOSSARY_PATH.read_text("utf-8"))
    return [
        (re.compile(rf"(?<!\w){re.escape(fold(src))}(?!\w)"), f"{src} — {ru}")
        for src, ru in entries.items()
    ]


def hits(text: str) -> list[str]:
    folded = fold(text)
    return [line for pattern, line in _patterns() if pattern.search(folded)][:MAX_HITS]
