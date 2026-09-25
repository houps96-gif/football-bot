import logging
import socket
import time

from bot import config, moderation, publish
from bot.live import Live, next_delay
from bot.matchday import Matchday
from bot.pipeline import Run
from bot.store import Store
from bot.telegram import Telegram, TelegramError

log = logging.getLogger(__name__)

LOCK_PORT = 47291
POLL_SECONDS = 25


def _single_instance() -> socket.socket:
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        raise SystemExit("Бот уже запущен в другом окне — вторая копия не нужна.")
    return lock


def _full_cycle(tg: Telegram, on_request: bool) -> None:
    before = Store.load().daily
    cards, results = before["cards"], before["results"]
    run = Run()
    run.run()
    after = Store.load()
    if on_request:
        moderation.send_menu(tg, f"Готово: новых карточек {after.daily['cards'] - cards}, "
                                 f"результатов матчей {after.daily['results'] - results}.")
    if "status" in run.commands:
        moderation.send_menu(tg, moderation.status_text(after))
    if "why" in run.commands:
        moderation.send_menu(tg, moderation.why_text(after))


def _poll(tg: Telegram) -> set[str]:
    st = Store.load()
    commands = moderation.process_updates(tg, st, wait=POLL_SECONDS)
    publish.publish_approved(tg, st)
    st.save()
    if "status" in commands:
        moderation.send_menu(tg, moderation.status_text(st))
    if "why" in commands:
        moderation.send_menu(tg, moderation.why_text(st))
    return commands


def _live_step(live: Live) -> int:
    try:
        st = Store.load()
        finished = live.check(st)
        delay = next_delay(st)
        st.save()
        if finished:
            Run().results_only()
        return delay
    except Exception:
        log.exception("живой режим: ошибка, повтор через 2 минуты")
        return 120


MATCHDAY_SECONDS = 300


def _matchday_step(matchday: Matchday) -> None:
    try:
        st = Store.load()
        matchday.step(st)
        st.save()
    except Exception:
        log.exception("матчи дня: ошибка, повтор через 5 минут")


def run_forever() -> None:
    lock = _single_instance()
    config.require_telegram()
    tg = Telegram(config.BOT_TOKEN)
    interval = config.LOOP_INTERVAL_MINUTES * 60
    next_cycle = 0.0
    log.info("бот запущен: полный цикл каждые %d мин, кнопки — сразу", config.LOOP_INTERVAL_MINUTES)
    try:
        moderation.send_menu(tg, "Бот запущен.")
    except TelegramError as e:
        log.warning("не удалось написать владельцу: %s", e)

    live = Live(tg)
    matchday = Matchday(tg)
    next_live = next_matchday = 0.0

    while True:
        if config.FEATURE_LIVE and time.monotonic() >= next_live:
            next_live = time.monotonic() + _live_step(live)
        if config.FEATURE_MATCHDAY and time.monotonic() >= next_matchday:
            _matchday_step(matchday)
            next_matchday = time.monotonic() + MATCHDAY_SECONDS
        try:
            refresh = False
            if time.monotonic() < next_cycle:
                refresh = "refresh" in _poll(tg)
                if refresh:
                    moderation.send_menu(tg, "Собираю свежие новости, это займёт пару минут…")
            if refresh or time.monotonic() >= next_cycle:
                _full_cycle(tg, on_request=refresh)
                next_cycle = time.monotonic() + interval
        except KeyboardInterrupt:
            log.info("остановлен")
            return
        except SystemExit:
            raise
        except TelegramError as e:
            log.error("Telegram: %s — повтор через минуту", e)
            time.sleep(60)
        except Exception:
            log.exception("цикл упал, следующий через %d мин", config.LOOP_INTERVAL_MINUTES)
            next_cycle = time.monotonic() + interval
            time.sleep(5)
