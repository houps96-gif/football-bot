import html
import logging

from bot import config
from bot.models import NewsItem
from bot.store import Store, age_hours, ts
from bot import results
from bot.telegram import Telegram, TelegramError

log = logging.getLogger(__name__)


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def card_text(item: NewsItem, status: str = "") -> str:
    lines = [
        f"<b>{esc(item.title_ru)}</b>",
        "",
        esc(item.summary_ru),
        "",
        f"{esc(item.category)} · {esc(item.league)} · важность {item.importance}/10 · {esc(item.source)}",
        f'<a href="{html.escape(item.url, quote=True)}">Оригинал</a>',
    ]
    if status:
        lines += ["", status]
    return "\n".join(lines)


def keyboard(item_id: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ Опубликовать", "callback_data": f"ok:{item_id}"},
        {"text": "❌ Отклонить", "callback_data": f"no:{item_id}"},
    ]]}


def send_card(tg: Telegram, item: NewsItem) -> tuple[int, bool]:
    message, is_photo = tg.send_post(config.ADMIN_CHAT_ID, card_text(item), item.image_url,
                                     reply_markup=keyboard(item.id), card=title_card_for(item))
    return message["message_id"], is_photo


def title_card_for(item: NewsItem):
    return lambda: results.title_card(config.LEAGUE_TITLES.get(item.league, "Футбол"), item.title_ru)


def update_card(tg: Telegram, card: dict, status: str) -> None:
    if not card.get("message_id"):
        return
    item = NewsItem.from_dict(card["item"])
    try:
        if card.get("photo"):
            tg.edit_message_caption(config.ADMIN_CHAT_ID, card["message_id"], card_text(item, status))
        else:
            tg.edit_message_text(config.ADMIN_CHAT_ID, card["message_id"], card_text(item, status))
    except TelegramError as e:
        log.warning("карточка не обновилась: %s", e)


def _answer(tg: Telegram, callback_id: str, text: str) -> None:
    try:
        tg.answer_callback(callback_id, text)
    except TelegramError:
        pass


BTN_REFRESH = "Обновить новости"
BTN_STATUS = "Статус"
BTN_WHY = "Почему нет новостей?"
MENU = {"keyboard": [[{"text": BTN_REFRESH}, {"text": BTN_STATUS}], [{"text": BTN_WHY}]],
        "resize_keyboard": True, "is_persistent": True}


def send_menu(tg: Telegram, text: str) -> None:
    tg.send_message(config.ADMIN_CHAT_ID, text, reply_markup=MENU)


def process_updates(tg: Telegram, st: Store, wait: int = 0) -> set[str]:
    updates = tg.get_updates(st.data["tg_offset"], allowed=["callback_query", "message"], wait=wait)
    commands: set[str] = set()
    for update in updates:
        st.data["tg_offset"] = update["update_id"] + 1
        if "callback_query" in update:
            _handle_callback(tg, st, update["callback_query"])
        elif "message" in update:
            command = _command(update["message"])
            if command == "start":
                send_menu(tg, "Кнопки внизу: «Обновить новости» — собрать свежее прямо сейчас, «Статус» — итоги за сутки.")
            elif command:
                commands.add(command)
    if updates:
        log.info("обработано апдейтов: %d", len(updates))
    return commands


def _command(message: dict) -> str | None:
    if str(message.get("from", {}).get("id")) != str(config.ADMIN_CHAT_ID):
        return None
    text = (message.get("text") or "").strip()
    if text in (BTN_REFRESH, "/refresh", "/update"):
        return "refresh"
    if text in (BTN_STATUS, "/status"):
        return "status"
    if text in (BTN_WHY, "/why"):
        return "why"
    if text.startswith("/start"):
        return "start"
    return None


def _local(stamp: str) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(stamp).astimezone(ZoneInfo(config.NIGHT_TZ)).strftime("%H:%M")


def _ago(stamp: str) -> str:
    minutes = int(age_hours(stamp) * 60)
    return f"{minutes} мин назад" if minutes < 60 else f"{minutes // 60} ч {minutes % 60} мин назад"


def why_text(st: Store) -> str:
    from datetime import datetime, timedelta

    d, day = st.data, st.daily
    waiting = len(d["pending"]) + len(d["approved"])
    published = sorted(d["published"].values())
    last_hour = [p for p in published if age_hours(p) < 1]
    streak = d.get("llm_fail_streak", 0)
    llm_used = day["llm_calls"] + day["llm_errors"]

    lines = []
    lines.append(f"Последняя новость в канале: {_local(published[-1])} ({_ago(published[-1])})."
                 if published else "Новостей в канале ещё не было.")
    per_hour = f" из {config.MAX_POSTS_PER_HOUR}" if config.MAX_POSTS_PER_HOUR else ""
    lines.append(f"Сегодня опубликовано {day['published']} из {config.MAX_POSTS_PER_DAY}, "
                 f"за последний час — {len(last_hour)}{per_hour}.")
    lines.append(f"Отобрано и ждёт публикации: {waiting}. Ждёт сортировки: {len(d['inbox'])}.")
    lines.append(f"Сегодня отсеяно: не по теме {day['off_topic']}, ниже порога {config.IMPORTANCE_MIN} — "
                 f"{day['below_threshold']}, дубли {day['duplicates']}.")
    if streak:
        err = d.get("llm_last_error", {})
        lines.append(f"Gemini: не отвечает {streak} запуск(а) подряд — {err.get('text', '')[:150]}")
    elif d.get("llm_last_ok"):
        lines.append(f"Gemini: работает, последний удачный запрос {_ago(d['llm_last_ok'])}.")
    lines.append(f"Запросов к Gemini сегодня: {llm_used} из {config.LLM_MAX_CALLS_PER_DAY}.")
    if d.get("last_run"):
        nxt = datetime.fromisoformat(d["last_run"]) + timedelta(minutes=config.LOOP_INTERVAL_MINUTES)
        lines.append(f"Последний сбор новостей: {_local(d['last_run'])}, следующий около {_local(nxt.isoformat())}.")
    if d["disabled_feeds"]:
        lines.append("Отключённые ленты: " + ", ".join(d["disabled_feeds"]))

    if day["published"] >= config.MAX_POSTS_PER_DAY:
        reason = "исчерпан дневной лимит постов — новости снова пойдут после полуночи (или поднимите MAX_POSTS_PER_DAY)."
    elif config.MAX_POSTS_PER_HOUR and len(last_hour) >= config.MAX_POSTS_PER_HOUR and waiting:
        free_at = datetime.fromisoformat(last_hour[0]) + timedelta(hours=1)
        reason = f"лимит {config.MAX_POSTS_PER_HOUR} поста в час — следующая новость выйдет около {_local(free_at.isoformat())}."
    elif streak:
        reason = "не отвечает Gemini — новости ждут в очереди и выйдут, когда он заработает."
    elif llm_used >= config.LLM_MAX_CALLS_PER_DAY:
        reason = "кончился дневной потолок запросов к Gemini — до полуночи новости не сортируются."
    elif waiting:
        reason = "новости есть и выйдут при ближайшем сборе. Можно не ждать — нажмите «Обновить новости»."
    else:
        reason = (f"в лентах просто нет свежих важных новостей: всё новое ниже порога {config.IMPORTANCE_MIN} "
                  "или повторяет уже опубликованное. Так бывает в тихие часы. Если хочется больше — "
                  "снизить IMPORTANCE_MIN в .env.")
    return "\n".join(esc(line) for line in lines) + f"\n\n<b>Причина:</b> {esc(reason)}"


def status_text(st: Store) -> str:
    d, day = st.data, st.daily
    waiting = sum(c["status"] == "sent" for c in d["cards"].values())
    lines = [
        f"Сегодня (UTC, {day['date']}):",
        f"собрано новых {day['collected']} · отсортировано {day['triaged']}",
        f"отсеяно: не по теме {day['off_topic']} · ниже порога {config.IMPORTANCE_MIN} — {day['below_threshold']}"
        f" · дубли {day['duplicates']}",
        f"отобрано {day['selected']} · карточек {day['cards']}",
        f"опубликовано {day['published']} из {config.MAX_POSTS_PER_DAY} · результатов матчей {day['results']}",
        f"запросов к LLM {day['llm_calls']} из {config.LLM_MAX_CALLS_PER_DAY} · ошибок {day['llm_errors']}",
        f"ждут твоего решения: {waiting} · в очереди на публикацию: {len(d['approved'])}",
        "премодерация: " + ("включена" if config.MODERATION else "выключена — новости публикуются сразу")
        + (" · сейчас ночной режим" if config.MODERATION and config.is_night() else ""),
    ]
    if d["disabled_feeds"]:
        lines.append("отключённые ленты: " + ", ".join(d["disabled_feeds"]))
    return "\n".join(lines)


def _handle_callback(tg: Telegram, st: Store, query: dict) -> None:
    if str(query["from"]["id"]) != str(config.ADMIN_CHAT_ID):
        _answer(tg, query["id"], "Нет доступа")
        return
    action, _, item_id = query.get("data", "").partition(":")
    card = st.data["cards"].get(item_id)
    if not card or card["status"] != "sent":
        _answer(tg, query["id"], "Карточка уже обработана или устарела")
        return

    if action == "ok":
        card["status"] = "approved"
        st.data["approved"].append(item_id)
        _answer(tg, query["id"], "✅ В очереди на публикацию")
        update_card(tg, card, "⏳ Одобрено, публикуется…")
    elif action == "no":
        card["status"] = "rejected"
        st.bump("rejected")
        _answer(tg, query["id"], "❌ Отклонено")
        update_card(tg, card, "❌ Отклонено")


def expire_cards(tg: Telegram, st: Store) -> None:
    for card in st.data["cards"].values():
        if card["status"] == "sent" and age_hours(card["sent"]) >= config.CARD_TTL_HOURS:
            card["status"] = "expired"
            update_card(tg, card, f"⌛ Не рассмотрено за {config.CARD_TTL_HOURS} ч — снято")


def new_card(item: NewsItem, message_id: int | None, status: str, photo: bool = False) -> dict:
    return {"item": item.to_dict(), "message_id": message_id, "photo": photo, "sent": ts(), "status": status}
