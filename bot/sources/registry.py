from bot import config
from bot.models import NewsItem
from bot.sources import rss


def collect(disabled: set[str]) -> tuple[list[NewsItem], dict[str, str]]:
    feeds = [(name, url) for name, url in config.FEEDS if name not in disabled]
    return rss.fetch(feeds)
