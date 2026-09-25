import logging
import re
from urllib.parse import unquote

import httpx2 as httpx

from bot import config
from bot.glossary import fold

log = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "FootballNewsBot/1.0 (https://github.com/houps96-gif/football-bot)"
CREDIT = "Фото: Википедия"
NOT_NAMES = {
    "Premier", "League", "Champions", "Europa", "Conference", "Nations", "Cup", "World", "Euro", "FA",
    "UEFA", "FIFA", "La", "Liga", "Serie", "Bundesliga", "Ligue", "The", "A", "B", "C", "After", "Before",
}
CAPS_RUN = re.compile(r"(?:\b[A-Z][a-z'’-]{1,}\b\s?)+")


def candidates(event: str) -> list[str]:
    seen: list[str] = []
    for run in CAPS_RUN.findall(event or ""):
        words = [w for w in run.split() if w not in NOT_NAMES]
        options = ([" ".join(words)] if len(words) == 2 else []) + words[::-1]
        for option in options:
            if len(option) > 2 and option not in seen:
                seen.append(option)
    return seen[:4]


def wiki_photo(event: str) -> str:
    with httpx.Client(timeout=config.HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        for name in candidates(event):
            try:
                data = client.get(API, params={
                    "action": "query", "format": "json", "redirects": 1,
                    "generator": "search", "gsrsearch": f"{name} {config.WIKI_HINT}".strip(), "gsrlimit": 1,
                    "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 1200,
                }).json()
            except (httpx.HTTPError, ValueError) as e:
                log.info("википедия: %s — %s", name, type(e).__name__)
                continue
            for page in (data.get("query") or {}).get("pages", {}).values():
                url = (page.get("thumbnail") or {}).get("source", "")
                filename = fold(unquote(url.rsplit("/", 1)[-1])).lower()
                if "/wikipedia/commons/" in url and fold(name.split()[-1]).lower() in filename:
                    log.info("фото из википедии: %s → %s", name, page.get("title"))
                    return url
    return ""
