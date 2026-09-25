import logging

from bot import config
from bot.models import NewsItem
from bot.sources import espn, rss

log = logging.getLogger(__name__)


def collect(disabled: set[str]) -> tuple[list[NewsItem], dict[str, str]]:
    feeds = [(name, url) for name, url in config.FEEDS if name not in disabled]
    items, errors = rss.fetch(feeds)
    try:
        espn_items, espn_errors = espn.fetch()
        items += espn_items
        for source, error in espn_errors.items():
            log.warning("%s: %s", source, error)
    except Exception as e:
        log.warning("ESPN API: %s", e)
    return items, errors
