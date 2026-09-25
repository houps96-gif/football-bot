import asyncio
import calendar
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx2 as httpx

from bot import config
from bot.models import NewsItem

TRACKING_PARAMS = {"cmp", "ito", "ref", "xtor", "src", "ocid"}
TRACKING_PREFIXES = ("utm_", "at_", "ns_")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
GOOGLE_SOURCE_SUFFIX = re.compile(r"\s+-\s+[^-]{2,40}$")


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (k, v) for k, v in parse_qsl(parts.query)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def news_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]


def clean_text(raw: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", raw or ""))).strip()


def _image(entry) -> str:
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key) or []:
            if media.get("url") and media.get("medium", "image") == "image":
                return media["url"]
    for enclosure in entry.get("enclosures") or []:
        if enclosure.get("type", "").startswith("image/") and enclosure.get("href"):
            return enclosure["href"]
    return ""


def _published(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc) if parsed else None


async def _fetch_one(client: httpx.AsyncClient, url: str):
    response = await client.get(url)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    feed["_debug"] = f"HTTP {response.status_code}, {response.url}, начало ответа: " \
                     f"{response.text[:150]!r}"
    return feed


async def _fetch_all(feeds: list[tuple[str, str]]):
    async with httpx.AsyncClient(
        timeout=config.HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": config.USER_AGENT},
    ) as client:
        return await asyncio.gather(*(_fetch_one(client, url) for _, url in feeds), return_exceptions=True)


def fetch(feeds: list[tuple[str, str]]) -> tuple[list[NewsItem], dict[str, str]]:
    results = asyncio.run(_fetch_all(feeds))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.MAX_ITEM_AGE_HOURS)
    items: list[NewsItem] = []
    errors: dict[str, str] = {}

    for (name, url), result in zip(feeds, results):
        via_google = "news.google.com" in url
        if isinstance(result, BaseException):
            errors[name] = f"{type(result).__name__}: {result}"[:200]
            continue
        if not result.entries:
            errors[name] = f"лента пустая или не разобралась ({result.get('_debug', '')})"
            continue
        for entry in result.entries:
            link = entry.get("link")
            title = clean_text(entry.get("title", ""))
            if via_google:
                title = GOOGLE_SOURCE_SUFFIX.sub("", title)
                entry["summary"] = ""
            if not link or not title:
                continue
            published = _published(entry)
            if published and published < cutoff:
                continue
            items.append(NewsItem(
                id=news_id(link),
                url=link,
                title=title,
                summary=clean_text(entry.get("summary", ""))[:500],
                source=name,
                published=published.isoformat() if published else "",
                image_url=_image(entry),
            ))
    return items, errors
