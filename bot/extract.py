import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx2 as httpx
import trafilatura

from bot import config

log = logging.getLogger(__name__)


@dataclass
class Article:
    text: str | None = None
    image_url: str = ""


def fetch_article(url: str) -> Article:
    try:
        response = httpx.get(
            url,
            timeout=config.HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": config.USER_AGENT},
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        log.info("статья не скачалась (%s): %s", type(e).__name__, url)
        return Article()

    page = response.text
    text = trafilatura.extract(page, url=url, include_comments=False, include_tables=False)
    metadata = trafilatura.extract_metadata(page, default_url=url)
    image = metadata.image if metadata and metadata.image else ""
    if image:
        image = urljoin(str(response.url), image)
    return Article(text=text[: config.ARTICLE_MAX_CHARS] if text else None, image_url=image)
