import argparse
import logging
import logging.handlers
import sys
import time

for stream in (sys.stdout, sys.stderr):
    if stream is not None:
        stream.reconfigure(encoding="utf-8")

from bot import config
from bot.pipeline import Run
from bot.telegram import Telegram


def whoami() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("Сначала впишите BOT_TOKEN в .env")
    updates = Telegram(config.BOT_TOKEN).get_updates(0, allowed=["message", "channel_post", "my_chat_member"])
    chats = {}
    for update in updates:
        for key in ("message", "channel_post", "my_chat_member"):
            if key in update:
                chat = update[key]["chat"]
                chats[chat["id"]] = f"{chat['type']:<8} {chat.get('title') or chat.get('username') or chat.get('first_name', '')}"
    if not chats:
        print("Ничего не нашлось. Напишите боту любое сообщение и опубликуйте пост в канале, потом повторите.")
    for chat_id, title in chats.items():
        print(f"{chat_id:>16}  {title}")
    print("\nprivate — это ваш ADMIN_CHAT_ID, channel — CHANNEL_ID.")


def setup_logging(to_file: bool) -> None:
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    if to_file:
        config.LOG_DIR.mkdir(exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            config.LOG_DIR / "bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "trafilatura"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(description="Бот новостей европейского футбола")
    parser.add_argument("--loop", action="store_true", help="работать постоянно (домашний компьютер)")
    parser.add_argument("--dry-run", action="store_true", help="без Telegram и без сохранения состояния")
    parser.add_argument("--limit", type=int, help="сколько новостей отсортировать за запуск")
    parser.add_argument("--whoami", action="store_true", help="показать chat_id для настройки")
    parser.add_argument("--cycles", type=int, default=1,
                        help="сколько проходов сделать за запуск (GitHub Actions не запускает чаще раза в 5 минут)")
    parser.add_argument("--every", type=int, default=150, help="пауза между проходами, секунд")
    parser.add_argument("--results-hours", type=int,
                        help=f"за сколько часов искать результаты матчей (по умолчанию {config.MATCH_MAX_AGE_HOURS})")
    args = parser.parse_args()
    setup_logging(to_file=args.loop)

    if args.whoami:
        whoami()
    elif args.loop:
        from bot.loop import run_forever
        run_forever()
    else:
        for cycle in range(args.cycles):
            if cycle:
                time.sleep(args.every)
            Run(dry_run=args.dry_run, limit=args.limit, results_hours=args.results_hours,
                extras=not args.dry_run).run()


if __name__ == "__main__":
    main()
