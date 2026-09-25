import logging
import re
from datetime import datetime, timedelta, timezone

import httpx2 as httpx

from bot import config
from bot.models import NewsItem
from bot.sources.rss import clean_text, is_not_news, news_id

log = logging.getLogger(__name__)

NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/news"
STORY_URL = "https://content.core.api.espn.com/v1/sports/news/{id}"
LEAGUES = ["eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "uefa.champions", "uefa.europa"]
STORY_ID = re.compile(r"espn\.[a-z.]+/.*/id/(\d+)")
SOURCE = "ESPN"


def fetch() -> tuple[list[NewsItem], dict[str, str]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.MAX_ITEM_AGE_HOURS)
    items: dict[str, NewsItem] = {}
    errors: dict[str, str] = {}
    with httpx.Client(timeout=config.HTTP_TIMEOUT) as client:
        for league in LEAGUES:
            try:
                response = client.get(NEWS_URL.format(league=league), params={"limit": 30})
                response.raise_for_status()
                articles = response.json().get("articles", [])
            except (httpx.HTTPError, ValueError) as e:
                errors[f"{SOURCE} {league}"] = type(e).__name__
                continue
            for a in articles:
                link = (a.get("links") or {}).get("web", {}).get("href", "")
                title = clean_text(a.get("headline", ""))
                if not link or not title or is_not_news(link, title) or a.get("type") not in (None, "Story", "HeadlineNews"):
                    continue
                published = a.get("published", "")
                try:
                    if published and datetime.fromisoformat(published.replace("Z", "+00:00")) < cutoff:
                        continue
                except ValueError:
                    pass
                images = [i.get("url") for i in a.get("images") or [] if i.get("url")]
                item = NewsItem(id=news_id(link), url=link, title=title,
                                summary=clean_text(a.get("description", ""))[:500], source=SOURCE,
                                published=published, image_url=images[0] if images else "")
                items[item.id] = item
    return list(items.values()), errors


def story_text(url: str) -> str | None:
    match = STORY_ID.search(url)
    if not match:
        return None
    try:
        response = httpx.get(STORY_URL.format(id=match.group(1)), timeout=config.HTTP_TIMEOUT)
        response.raise_for_status()
        story = (response.json().get("headlines") or [{}])[0].get("story", "")
    except (httpx.HTTPError, ValueError, IndexError) as e:
        log.info("ESPN: текст статьи не получен (%s)", type(e).__name__)
        return None
    text = clean_text(story)
    return text[: config.ARTICLE_MAX_CHARS] if text else None
