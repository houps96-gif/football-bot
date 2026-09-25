import logging
import re

from bot import config, glossary
from bot.llm import LLM
from bot.llm.base import SUMMARY_SCHEMA
from bot.models import NewsItem

log = logging.getLogger(__name__)

SYSTEM = config.SUMMARY_SYSTEM


def build_prompt(item: NewsItem, text: str | None) -> str:
    parts = []
    hits = glossary.hits(" ".join([item.title, item.summary, text or ""]))
    if hits:
        parts.append("Глоссарий (обязательные написания):\n" + "\n".join(hits))
    parts.append(f"Источник: {item.source}\nЗаголовок: {item.title}")
    if text:
        parts.append("Текст статьи:\n" + text)
    else:
        parts.append(f"Полный текст недоступен, есть только анонс:\n{item.summary}")
    return "\n\n".join(parts)


NOT_RUSSIAN = str.maketrans({"і": "и", "І": "И", "ї": "и", "Ї": "И", "є": "е", "Є": "Е", "ґ": "г", "Ґ": "Г"})


def clean_ru(text: str) -> str:
    return str(text or "").strip().translate(NOT_RUSSIAN)


LATIN_WORD = re.compile(r"[A-Za-z]{2,}")

latin_retries = 0


def latin_words(result: dict) -> list[str]:
    text = " ".join(clean_ru(result.get(k)) for k in ("title_ru", "summary_ru"))
    return list(dict.fromkeys(LATIN_WORD.findall(text)))


def summarize(llm: LLM, item: NewsItem, text: str | None) -> dict:
    global latin_retries
    prompt = build_prompt(item, text)
    result = llm.generate_json(SYSTEM, prompt, SUMMARY_SCHEMA, max_tokens=4096)

    found = latin_words(result)
    if found:
        latin_retries += 1
        log.info("пересказ: латиница в тексте (%s), переспрашиваю модель", ", ".join(found))
        note = ("\n\nВ прошлой версии остались слова латиницей: " + ", ".join(found)
                + ". Перепиши заголовок и текст полностью на русском: имена, клубы и аббревиатуры — "
                "кириллицей, без единого латинского слова.")
        try:
            retry = llm.generate_json(SYSTEM, prompt + note, SUMMARY_SCHEMA, max_tokens=4096)
        except Exception as e:
            log.info("пересказ: повторная попытка не удалась (%s), оставляю первый вариант", e)
        else:
            left = latin_words(retry)
            if retry.get("title_ru") and retry.get("summary_ru") and len(left) < len(found):
                result = retry
            log.info("пересказ: после повтора латиницы %d (было %d)", len(left), len(found))

    category = result.get("category")
    return {
        "title_ru": clean_ru(result.get("title_ru")),
        "summary_ru": clean_ru(result.get("summary_ru")),
        "category": category if category in config.CATEGORIES else config.CATEGORIES[-1],
    }
