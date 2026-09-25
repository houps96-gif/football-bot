import html
import logging
import time

from bot import config
from bot.moderation import esc, title_card_for, update_card
from bot.models import NewsItem
from bot.store import Store, published_last_hour, ts
from bot.telegram import Telegram, TelegramError

log = logging.getLogger(__name__)

MAX_PUBLISH_ERRORS = 3


def post_text(item: NewsItem) -> str:
    footer = f'<a href="{html.escape(item.url, quote=True)}">{esc(item.source)}</a>'
    if item.league and item.league != "Другое":
        footer += f" · #{item.league}"
    if item.image_credit:
        footer += f" · {esc(item.image_credit)}"
    return f"<b>{esc(item.title_ru)}</b>\n\n{esc(item.summary_ru)}\n\n{footer}"


def publish_approved(tg: Telegram, st: Store) -> None:
    queue = st.data["approved"]
    cards = st.data["cards"]
    first = True
    for item_id in list(queue):
        if st.daily["published"] >= config.MAX_POSTS_PER_DAY:
            log.info("дневной лимит постов исчерпан, в очереди осталось %d", len(queue))
            return
        if config.MAX_POSTS_PER_HOUR and published_last_hour(st.data) >= config.MAX_POSTS_PER_HOUR:
            log.info("лимит постов в час, в очереди осталось %d — выйдут позже", len(queue))
            return
        card = cards.get(item_id)
        if not card:
            queue.remove(item_id)
            continue
        if not first:
            time.sleep(config.PUBLISH_DELAY_SECONDS)
        first = False

        try:
            item = NewsItem.from_dict(card["item"])
            tg.send_post(config.CHANNEL_ID, post_text(item), item.image_url, card=title_card_for(item))
        except TelegramError as e:
            card["errors"] = card.get("errors", 0) + 1
            log.error("пост не опубликован (%d-я попытка): %s", card["errors"], e)
            if card["errors"] >= MAX_PUBLISH_ERRORS:
                queue.remove(item_id)
                card["status"] = "failed"
                update_card(tg, card, f"⚠️ Не опубликовано: {esc(str(e))}")
            continue

        queue.remove(item_id)
        card["status"] = "published"
        st.data["published"][item_id] = ts()
        st.bump("published")
        st.save()
        update_card(tg, card, "✅ Опубликовано")
