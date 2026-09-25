import json
import logging
import time
from typing import Callable

import httpx2 as httpx

log = logging.getLogger(__name__)


NO_PREVIEW = {"is_disabled": True}


def photo_preview(url: str) -> dict:
    return {"url": url, "prefer_large_media": True, "show_above_text": True}


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token: str):
        self._base = f"https://api.telegram.org/bot{token}/"
        self._client = httpx.Client(timeout=60)

    def call(self, method: str, files: dict | None = None, **params):
        params = {k: v for k, v in params.items() if v is not None}
        if files:
            params = {k: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for k, v in params.items()}
        for attempt in range(3):
            try:
                if files:
                    response = self._client.post(self._base + method, data=params, files=files)
                else:
                    response = self._client.post(self._base + method, json=params)
                data = response.json()
            except (httpx.TransportError, ValueError) as e:
                if attempt == 2:
                    raise TelegramError(f"{method}: {type(e).__name__}") from None
                time.sleep(2)
                continue
            if data.get("ok"):
                return data["result"]
            retry_after = data.get("parameters", {}).get("retry_after")
            if response.status_code == 429 and retry_after and attempt < 2:
                log.warning("Telegram просит подождать %s с", retry_after)
                time.sleep(retry_after + 1)
                continue
            raise TelegramError(f"{method}: {data.get('description')}")
        raise TelegramError(f"{method}: не удалось после повторов")

    def get_updates(self, offset: int, allowed: list[str] | None = None, wait: int = 0) -> list[dict]:
        return self.call("getUpdates", offset=offset, timeout=wait, allowed_updates=allowed or ["callback_query"])

    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None,
                     link_preview: dict | None = NO_PREVIEW, silent: bool = False) -> dict:
        return self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            link_preview_options=link_preview,
            disable_notification=silent or None,
        )

    def delete_message(self, chat_id: str, message_id: int) -> None:
        self.call("deleteMessage", chat_id=chat_id, message_id=message_id)

    def edit_message_text(self, chat_id: str, message_id: int, text: str, reply_markup: dict | None = None,
                          link_preview: dict | None = NO_PREVIEW) -> None:
        self.call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            link_preview_options=link_preview,
        )

    def send_photo(self, chat_id: str, photo_url: str, caption: str, reply_markup: dict | None = None) -> dict:
        return self.call(
            "sendPhoto",
            chat_id=chat_id,
            photo=photo_url,
            caption=caption[:1024],
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    def send_photo_file(self, chat_id: str, png: bytes, caption: str, reply_markup: dict | None = None) -> dict:
        return self.call(
            "sendPhoto",
            files={"photo": ("image.png", png, "image/png")},
            chat_id=chat_id,
            caption=caption[:1024],
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    def edit_message_caption(self, chat_id: str, message_id: int, caption: str, reply_markup: dict | None = None) -> None:
        self.call(
            "editMessageCaption",
            chat_id=chat_id,
            message_id=message_id,
            caption=caption[:1024],
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    def send_post(self, chat_id: str, text: str, image_url: str = "", reply_markup: dict | None = None,
                  card: Callable[[], bytes] | None = None) -> tuple[dict, bool]:
        if image_url:
            try:
                return self.send_photo(chat_id, image_url, text, reply_markup), True
            except TelegramError as e:
                log.info("картинка статьи не загрузилась (%s)", e)
        if card:
            try:
                return self.send_photo_file(chat_id, card(), text, reply_markup), True
            except TelegramError as e:
                log.info("карточка не отправилась (%s), отправляю текстом", e)
        return self.send_message(chat_id, text, reply_markup), False

    def answer_callback(self, callback_id: str, text: str) -> None:
        self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
