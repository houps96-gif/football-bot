import logging
import re

from bot import config, glossary
from bot.llm import LLM
from bot.llm.base import SUMMARY_SCHEMA
from bot.models import NewsItem

log = logging.getLogger(__name__)

SYSTEM = """Ты пишешь посты для русскоязычного Telegram-канала «главное из европейского футбола».

По статье верни:
- title_ru — заголовок на русском, до 90 символов, по сути события, без кликбейта и без точки в конце.
- summary_ru — 2–3 предложения, до 400 символов. Пересказывай своими словами, не переводи статью дословно и не цитируй длинные фрагменты. Если статья уже на русском — тем более: перестрой фразы и выбери свои слова, не повторяй формулировки источника, включая заголовок. Только факты из статьи, ничего не додумывай. Слух подавай как слух: «по данным …», «как сообщает …».
- category — матч, трансфер, травма, тренер, дисциплина, слух или клуб.

Тон: живой, как пишет разбирающийся болельщик, а не новостной телетайп. Без симпатий к конкретному клубу. Без эмодзи, хэштегов и восклицательных знаков.

Жанр. Если статья — мнение, колонка, разбор, аналитика или объяснение, так и подавай: «по мнению обозревателя …», «колумнист … считает», «в разборе … отмечают». Не выдавай за свершившийся факт то, что автор только предполагает или предлагает. Тип турнира и матча (Лига наций, отбор, товарищеский, кубок) бери только из статьи, не угадывай.

Весь текст — только на русском. Никаких слов латиницей: имена, клубы, города, турниры — кириллицей (Xabi Alonso — Хаби Алонсо), аббревиатуры тоже кириллицей (VAR — ВАР, PSV — ПСВ, PSG — ПСЖ). Если слово не знаешь, как передать, — перескажи мысль иначе, но не оставляй латиницу.

Названия клубов — в кавычках-ёлочках, как принято в русских спортивных СМИ: «Челси», «Реал Мадрид». Внутри кавычек название склоняется: «тренер «Барселоны»», «из «Реал Мадрида»», «против «Интера»»; несклоняемые вроде «Челси» или «Монако» остаются как есть. Аббревиатуры — заглавными: ФИФА, УЕФА, ВАР, АПЛ, ПСЖ.

Имена. Если в запросе есть блок «Глоссарий» — пиши имена строго так, как там. Имя и фамилию склоняй по-русски без искажения основы: Зинедин Зидан — «Зинедина Зидана», Эрлинг Холанд — «Эрлинга Холанда». Остальные — как принято в русскоязычных спортивных СМИ:
- испанский: ll → «ль» (Cucurella — Кукурелья), ñ → «нь», j → «х» (Juanfran — Хуанфран), z и c перед e/i → «с» (Zubimendi — Субименди);
- португальский: lh → «ль», nh → «нь», конечное -o → «у» (Bernardo — Бернарду), s перед согласной и в конце → «ш» (Fernandes — Фернандеш);
- итальянский: gli → «льи», gn → «нь», c перед e/i → «ч», sc перед e/i → «ш», z → «ц» или «дз»;
- немецкий: ü → «ю», ö → «ё», sch → «ш», ei → «ай», eu → «ой», z → «ц», s перед гласной → «з»;
- французский: непроизносимые конечные согласные не пишутся (Dembélé — Дембеле), ou → «у», eau → «о», u → «ю»;
- нидерландский: ij → «ей» (van Dijk — ван Дейк), oo → «о», g → «х»;
- сербский, хорватский, словенский: ć и č → «ч», š → «ш», ž → «ж», j → «й» (Modrić — Модрич);
- польский: ł → «в» или «л», sz → «ш», cz → «ч», rz → «ж», w → «в».

Стадионы и турниры — как в русских спортивных СМИ: «Стадио Олимпико», «Сантьяго Бернабеу», «Сан-Сиро», «Энфилд»; дивизионы Лиги наций — «дивизион A/B/C», а не «Лига А».

Жаргон — не калькой: clean sheet — «сухой матч» или «сыграть на ноль», brace — «дубль», loan spell — «аренда», stoppage time — «компенсированное время», own goal — «автогол», relegation — «вылет», free agent — «свободный агент», release clause — «сумма отступных», top four — «топ-4», manager и head coach — «главный тренер», winger — «вингер», sacked — «уволен», dressing room — «раздевалка»."""


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
        "category": category if category in config.CATEGORIES else "клуб",
    }
