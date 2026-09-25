import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int_env(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


LLM_PROVIDER = _env("LLM_PROVIDER", "gemini").lower()
GEMINI_API_KEY = _env("GEMINI_API_KEY")
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")

BOT_TOKEN = _env("BOT_TOKEN")
CHANNEL_ID = _env("CHANNEL_ID")
ADMIN_CHAT_ID = _env("ADMIN_CHAT_ID")


GEMINI_MODELS = [
    m.strip()
    for m in _env("GEMINI_MODELS", "gemini-flash-lite-latest,gemini-flash-latest,gemini-3.5-flash-lite").split(",")
    if m.strip()
]
CLAUDE_MODEL = _env("CLAUDE_MODEL", "claude-haiku-4-5")

LLM_MIN_INTERVAL_SECONDS = _int_env("LLM_MIN_INTERVAL_SECONDS", 6)
LLM_MAX_CALLS_PER_DAY = _int_env("LLM_MAX_CALLS_PER_DAY", 400)


FEEDS = [
    ("BBC", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
    ("Guardian", "https://www.theguardian.com/football/rss"),
    ("Sky Sports", "https://www.skysports.com/rss/11095"),
    ("ESPN", "https://www.espn.com/espn/rss/soccer/news"),
    ("Independent", "https://www.independent.co.uk/sport/football/rss"),
    ("football.london", "https://www.football.london/?service=rss"),
    ("Sports.ru", "https://www.sports.ru/rss/topnews/football.xml"),
    ("Marca", "https://e00-marca.uecdn.es/rss/futbol/primera-division.xml"),
    ("AS", "https://feeds.as.com/mrss-s/pages/as/site/as.com/section/futbol/portada/"),
    ("Mundo Deportivo", "https://www.mundodeportivo.com/rss/futbol"),
    ("Gazzetta", "https://www.gazzetta.it/rss/calcio.xml"),
    ("Football Italia", "https://football-italia.net/feed/"),
    ("Kicker", "https://newsfeed.kicker.de/news/aktuell"),
    ("L'Équipe", "https://dwh.lequipe.fr/api/edito/rss?path=/Football/"),
    ("RMC Sport", "https://rmcsport.bfmtv.com/rss/football/"),
]


LEAGUES = ["АПЛ", "ЛаЛига", "СерияА", "Бундеслига", "Лига1", "ЛЧ", "ЛЕ", "ЛК", "Сборные", "Другое"]
MAIN_LEAGUES = set(LEAGUES) - {"Другое"}
LEAGUE_TITLES = {
    "АПЛ": "АПЛ", "ЛаЛига": "Ла Лига", "СерияА": "Серия А", "Бундеслига": "Бундеслига",
    "Лига1": "Лига 1", "ЛЧ": "Лига чемпионов", "ЛЕ": "Лига Европы", "ЛК": "Лига конференций",
    "Сборные": "Сборные", "Другое": "Футбол",
}

CATEGORIES = ["матч", "трансфер", "травма", "тренер", "дисциплина", "слух", "клуб"]


TOP_TEAMS = {
    359: "Arsenal",
    363: "Chelsea",
    382: "Manchester City",
    360: "Manchester United",
    364: "Liverpool",
    367: "Tottenham Hotspur",
    86: "Real Madrid",
    83: "Barcelona",
    132: "Bayern Munich",
    124: "Borussia Dortmund",
    103: "AC Milan",
    110: "Internazionale",
    104: "AS Roma",
    114: "Napoli",
    111: "Juventus",
    1068: "Atlético Madrid",
    160: "Paris Saint-Germain",
    1929: "Benfica",
    437: "FC Porto",
    448: "England",
    481: "Germany",
    478: "France",
    482: "Portugal",
    449: "Netherlands",
    164: "Spain",
    205: "Brazil",
    202: "Argentina",
    162: "Italy",
    459: "Belgium",
    477: "Croatia",
    212: "Uruguay",
    471: "Poland",
    464: "Norway",
    457: "Ukraine",
    203: "Mexico",
    660: "United States",
}

MATCH_COMPETITIONS = [
    ("eng.1", "АПЛ", "АПЛ"),
    ("esp.1", "ЛаЛига", "Ла Лига"),
    ("ita.1", "СерияА", "Серия А"),
    ("ger.1", "Бундеслига", "Бундеслига"),
    ("fra.1", "Лига1", "Лига 1"),
    ("por.1", "Португалия", "Чемпионат Португалии"),
    ("uefa.champions", "ЛЧ", "Лига чемпионов"),
    ("uefa.europa", "ЛЕ", "Лига Европы"),
    ("uefa.europa.conf", "ЛК", "Лига конференций"),
    ("eng.fa", "КубокАнглии", "Кубок Англии"),
    ("eng.league_cup", "КубокЛиги", "Кубок английской лиги"),
    ("esp.copa_del_rey", "КубокИспании", "Кубок Испании"),
    ("ita.coppa_italia", "КубокИталии", "Кубок Италии"),
    ("ger.dfb_pokal", "КубокГермании", "Кубок Германии"),
    ("eng.charity", "СуперкубокАнглии", "Суперкубок Англии"),
    ("esp.super_cup", "СуперкубокИспании", "Суперкубок Испании"),
    ("ita.super_cup", "СуперкубокИталии", "Суперкубок Италии"),
    ("ger.super_cup", "СуперкубокГермании", "Суперкубок Германии"),
    ("fifa.cwc", "КЧМ", "Клубный чемпионат мира"),
    ("fifa.world", "ЧМ", "Чемпионат мира"),
    ("uefa.euro", "Евро", "Чемпионат Европы"),
    ("uefa.nations", "ЛигаНаций", "Лига наций"),
    ("fifa.worldq.uefa", "ОтборЧМ", "Отбор ЧМ, Европа"),
    ("fifa.worldq.conmebol", "ОтборЧМ", "Отбор ЧМ, Южная Америка"),
    ("uefa.euroq", "ОтборЕвро", "Отбор Евро"),
    ("conmebol.america", "КопаАмерика", "Кубок Америки"),
    ("fifa.worldq.concacaf", "ОтборЧМ", "Отбор ЧМ, КОНКАКАФ"),
    ("concacaf.gold", "ЗолотойКубок", "Золотой кубок КОНКАКАФ"),
    ("concacaf.nations.league", "ЛигаНаций", "Лига наций КОНКАКАФ"),
    ("fifa.friendly", "Сборные", "Товарищеский матч"),
]
MATCH_MAX_AGE_HOURS = 12


IMPORTANCE_MIN = _int_env("IMPORTANCE_MIN", 6)
IMPORTANCE_MIN_OTHER = _int_env("IMPORTANCE_MIN_OTHER", 7)
AUTO_PUBLISH_THRESHOLD = _int_env("AUTO_PUBLISH_THRESHOLD", 0)

MODERATION = bool(_int_env("MODERATION", 0))

NIGHT_TZ = _env("NIGHT_TZ", "Europe/Warsaw")
NIGHT_FROM_HOUR = _int_env("NIGHT_FROM_HOUR", 0)
NIGHT_TO_HOUR = _int_env("NIGHT_TO_HOUR", 10)


MATCHDAY_HOUR = _int_env("MATCHDAY_HOUR", 9)


def local_hour() -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(NIGHT_TZ)).hour


def auto_publish_now() -> bool:
    return not MODERATION or is_night()


def is_night() -> bool:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if NIGHT_FROM_HOUR == NIGHT_TO_HOUR:
        return False
    hour = datetime.now(ZoneInfo(NIGHT_TZ)).hour
    if NIGHT_FROM_HOUR < NIGHT_TO_HOUR:
        return NIGHT_FROM_HOUR <= hour < NIGHT_TO_HOUR
    return hour >= NIGHT_FROM_HOUR or hour < NIGHT_TO_HOUR

MAX_POSTS_PER_DAY = _int_env("MAX_POSTS_PER_DAY", 50)
MAX_POSTS_PER_HOUR = _int_env("MAX_POSTS_PER_HOUR", 0)
MAX_CARDS_PER_DAY = _int_env("MAX_CARDS_PER_DAY", 80)
MAX_TRIAGE_PER_RUN = 120
TRIAGE_BATCH_SIZE = 40
MAX_SUMMARIES_PER_RUN = 8

MAX_ITEM_AGE_HOURS = 24
CARD_TTL_HOURS = 12
PENDING_TTL_HOURS = 12
MAX_LLM_TRIES = 3
FEED_MAX_FAILURES = 5

DUP_THRESHOLD = 85
SEEN_TTL_DAYS = 7
EVENTS_TTL_HOURS = 48

LOOP_INTERVAL_MINUTES = _int_env("LOOP_INTERVAL_MINUTES", 20)
LOG_DIR = ROOT / "logs"
PUBLISH_DELAY_SECONDS = 3.5
ARTICLE_MAX_CHARS = 6000
HTTP_TIMEOUT = 10
USER_AGENT = _env("USER_AGENT", "Mozilla/5.0 (compatible; football-news-bot/1.0)")


STATE_PATH = ROOT / "data" / "state.json"
GLOSSARY_PATH = ROOT / "data" / "glossary.json"
NAMES_PATH = ROOT / "data" / "names_ru.json"
FONTS_DIR = ROOT / "assets" / "fonts"
PREVIEW_DIR = ROOT / "preview"
CHANNEL_TITLE = _env("CHANNEL_TITLE", "Футбол Европы")


def require_telegram() -> None:
    missing = [n for n in ("BOT_TOKEN", "CHANNEL_ID", "ADMIN_CHAT_ID") if not globals()[n]]
    if missing:
        raise SystemExit(f"Не заданы {', '.join(missing)} — заполните .env или запустите с --dry-run")
