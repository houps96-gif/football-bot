import logging
import time

from bot import config, extract, moderation, publish, results
from bot.dedup import is_duplicate
from bot.live import Live, result_competitions
from bot.llm import LLM, LLMError, get_llm
from bot.matchday import Matchday
from bot.models import NewsItem
from bot.sources import matches, registry
from bot.store import Store, age_hours, published_last_hour, ts
from bot.summarize import summarize
from bot.telegram import Telegram, TelegramError
from bot.triage import triage

log = logging.getLogger(__name__)


class Run:
    def __init__(self, dry_run: bool = False, limit: int | None = None, results_hours: int | None = None,
                 extras: bool = False):
        self.extras = extras
        self.dry_run = dry_run
        self.limit = limit
        self.results_hours = results_hours or config.MATCH_MAX_AGE_HOURS
        self.st = Store.load()
        self.tg: Telegram | None = None
        self.notes: list[str] = []
        self.commands: set[str] = set()
        self.llm_ok = False
        self.llm_error = ""
        self.triage_log: list[tuple] = []


    def run(self) -> None:
        if not self.dry_run:
            config.require_telegram()
            self.tg = Telegram(config.BOT_TOKEN)
        try:
            finished_day = self.st.roll_day()
            if finished_day and self.tg:
                self.send_admin(daily_report(finished_day, finished_day.get("disabled_feeds", [])))

            if self.tg:
                self.commands = moderation.process_updates(self.tg, self.st)
                publish.publish_approved(self.tg, self.st)
                moderation.expire_cards(self.tg, self.st)
                self.st.save()

            self.collect()
            llm = get_llm()
            if self.extras and self.tg:
                Live(self.tg).check(self.st)
            self.post_results(llm)
            self.triage_inbox(llm)
            self.summarize_pending(llm)

            if self.tg:
                publish.publish_approved(self.tg, self.st)
                self.check_alerts()
            if self.extras and self.tg:
                Matchday(self.tg).step(self.st)
                self.answer_commands()
            self.st.prune()
        except Exception as e:
            if self.tg:
                self.send_admin(f"⚠️ Запуск упал: {type(e).__name__}: {moderation.esc(str(e))[:500]}")
            raise
        finally:
            if not self.dry_run:
                self.st.save()

        if self.notes and self.tg:
            self.send_admin("\n\n".join(moderation.esc(n) for n in self.notes))
        if self.dry_run:
            self.print_triage()
        log.info("итог запуска: %s", {k: v for k, v in self.st.daily.items() if k != "date"})

    def answer_commands(self) -> None:
        if "refresh" in self.commands:
            moderation.send_menu(self.tg, f"Собрал свежее. Сегодня опубликовано {self.st.daily['published']} "
                                          f"из {config.MAX_POSTS_PER_DAY}.")
        if "status" in self.commands:
            moderation.send_menu(self.tg, moderation.status_text(self.st))
        if "why" in self.commands:
            moderation.send_menu(self.tg, moderation.why_text(self.st))

    def results_only(self) -> None:
        config.require_telegram()
        self.tg = Telegram(config.BOT_TOKEN)
        try:
            self.post_results(get_llm())
        finally:
            self.st.save()

    def llm_allowed(self) -> bool:
        used = self.st.daily["llm_calls"] + self.st.daily["llm_errors"]
        if used < config.LLM_MAX_CALLS_PER_DAY:
            return True
        if not self.st.daily.get("llm_cap_noted"):
            self.st.daily["llm_cap_noted"] = True
            self.notes.append(f"⚠️ Кончился наш дневной потолок запросов к Gemini ({config.LLM_MAX_CALLS_PER_DAY}). "
                              "До полуночи новости не сортируются и не выходят; результаты матчей выходят. "
                              "Поднять потолок — LLM_MAX_CALLS_PER_DAY в .env.")
        log.warning("дневной потолок LLM (%d) достигнут", config.LLM_MAX_CALLS_PER_DAY)
        return False

    def check_alerts(self) -> None:
        d, day = self.st.data, self.st.daily
        sent = day.setdefault("alerts", [])
        waiting = len(d["pending"]) + len(d["approved"])

        def alert(key: str, text: str) -> None:
            if key not in sent:
                sent.append(key)
                self.notes.append(text)

        if day["published"] >= config.MAX_POSTS_PER_DAY and waiting:
            alert("posts_day",
                  f"⚠️ Дневной лимит постов ({config.MAX_POSTS_PER_DAY}) исчерпан. Отобранных новостей "
                  f"в очереди: {waiting}. До полуночи выходят только результаты матчей и «Матчи дня». "
                  "Поднять лимит — MAX_POSTS_PER_DAY в .env.")
        if config.MAX_POSTS_PER_HOUR and day["expired"] >= 5:
            alert("expired",
                  f"⚠️ Лимит {config.MAX_POSTS_PER_HOUR} поста в час не успевает: сегодня {day['expired']} "
                  "отобранных новостей устарели, так и не выйдя в канал. Поднять — MAX_POSTS_PER_HOUR в .env.")

        d["last_run"] = ts()
        if self.llm_ok:
            d["llm_last_ok"] = ts()
        if self.llm_error:
            d["llm_last_error"] = {"text": self.llm_error[:300], "ts": ts()}

        if self.llm_ok:
            if d.get("llm_down_alerted"):
                self.notes.append("✅ Gemini снова отвечает, новости идут как обычно.")
            d["llm_down_alerted"], d["llm_fail_streak"] = False, 0
        elif self.llm_error:
            d["llm_fail_streak"] = streak = d.get("llm_fail_streak", 0) + 1
            if streak >= 3 and not d.get("llm_down_alerted"):
                d["llm_down_alerted"] = True
                if "429" in self.llm_error and "503" not in self.llm_error:
                    self.notes.append(
                        "⚠️ Похоже, закончилась бесплатная квота Gemini (Google отвечает 429). Новости ждут "
                        "в очереди и выйдут, когда квота сбросится (раз в сутки, около 9:00–10:00 по Варшаве). "
                        "Результаты матчей выходят. Если так будет часто — нужен второй ключ Gemini или ключ Claude.")
                else:
                    self.notes.append(
                        f"⚠️ Gemini не отвечает уже около {streak * config.LOOP_INTERVAL_MINUTES} минут "
                        f"({self.llm_error[:200]}). Обычно это временная перегрузка бесплатного тарифа: "
                        "новости ждут в очереди и выйдут, когда он оживёт. Я напишу, когда заработает.")

        published = list(d["published"].values())
        last = max(published) if published else None
        if last and age_hours(last) >= 3 and config.local_hour() >= 9 and d.get("silence_alerted_for") != last:
            d["silence_alerted_for"] = last
            if day["published"] >= config.MAX_POSTS_PER_DAY:
                reason = "кончился дневной лимит постов"
            elif d.get("llm_fail_streak"):
                reason = "не отвечает Gemini"
            elif not waiting and not d["inbox"]:
                reason = "в лентах нет свежих важных новостей — так бывает в тихие часы"
            else:
                reason = "причина неочевидна — проверьте logs\\bot.log"
            self.notes.append(
                f"⚠️ В канале нет новостей уже {int(age_hours(last))} ч. Похоже, {reason}. "
                f"Сейчас: ждут публикации {waiting}, в очереди на сортировку {len(d['inbox'])}, "
                f"опубликовано сегодня {day['published']} из {config.MAX_POSTS_PER_DAY}.")

    def send_admin(self, text: str) -> None:
        try:
            self.tg.send_message(config.ADMIN_CHAT_ID, text)
        except TelegramError as e:
            log.error("не удалось написать владельцу: %s", e)


    def collect(self) -> None:
        d = self.st.data
        disabled = set(d["disabled_feeds"])
        items, errors = registry.collect(disabled)

        for name, _ in config.FEEDS:
            if name in disabled:
                continue
            if name not in errors:
                d["feed_failures"].pop(name, None)
                continue
            fails = d["feed_failures"][name] = d["feed_failures"].get(name, 0) + 1
            log.warning("лента %s: %s (ошибок подряд: %d)", name, errors[name], fails)
            if fails >= config.FEED_MAX_FAILURES:
                d["disabled_feeds"].append(name)
                self.notes.append(f"⚠️ Лента {name} отключена после {fails} ошибок подряд: {errors[name]}")

        new = 0
        for item in items:
            if item.id in d["seen"]:
                continue
            d["seen"][item.id] = ts()
            d["inbox"][item.id] = {"item": item.to_dict(), "added": ts(), "tries": 0}
            new += 1
        self.st.bump("collected", new)
        log.info("лент: %d, записей: %d, новых: %d, ждут сортировки: %d",
                 len(config.FEEDS) - len(disabled), len(items), new, len(d["inbox"]))

    def post_results(self, llm: LLM) -> None:
        d = self.st.data
        competitions = None if self.results_hours != config.MATCH_MAX_AGE_HOURS else result_competitions(self.st)
        found, errors = matches.fetch_finished(self.results_hours, competitions)
        for error in errors:
            log.warning("результаты: %s", error)
        new = [m for m in found if m.id not in d["matches_posted"]]
        log.info("завершённых матчей топ-команд: %d, новых: %d", len(found), len(new))
        if not new:
            return

        cache = d["names_ru"]
        try:
            names = results.match_names(new)
            if results.missing_names(names, cache):
                if not self.llm_allowed():
                    raise LLMError("дневной потолок")
                self.st.bump("llm_calls")
            ru = results.translate(llm, names, cache)
        except LLMError as e:
            self.st.bump("llm_errors")
            if str(e) != "дневной потолок":
                self.llm_error = str(e)
            log.error("имена для результатов не перевелись: %s", e)
            ru = results.lookup(names, cache)
            for m in new:
                d["match_tries"][m.id] = d["match_tries"].get(m.id, 0) + 1
            new = [m for m in new if d["match_tries"][m.id] >= config.MAX_LLM_TRIES]

        for i, m in enumerate(new):
            text, png = results.post_text(m, ru), results.scoreboard(m, ru)
            d["events"].append({"event": m.event, "id": f"match:{m.id}", "ts": ts()})
            if self.dry_run:
                config.PREVIEW_DIR.mkdir(exist_ok=True)
                path = config.PREVIEW_DIR / f"match_{m.id}.png"
                path.write_bytes(png)
                print("\n" + "─" * 70 + f"\n[результат · картинка: {path}]\n{text}")
                continue
            if i:
                time.sleep(config.PUBLISH_DELAY_SECONDS)
            self.tg.send_photo_file(config.CHANNEL_ID, png, text)
            d["matches_posted"][m.id] = ts()
            self.st.bump("results")
            self.st.save()

    def triage_inbox(self, llm: LLM) -> None:
        d = self.st.data
        inbox = d["inbox"]
        _drop_stale(inbox, config.MAX_ITEM_AGE_HOURS)

        ids = sorted(inbox, key=lambda i: inbox[i]["item"]["published"] or inbox[i]["added"], reverse=True)
        ids = ids[: self.limit or config.MAX_TRIAGE_PER_RUN]
        recent = [e["event"] for e in d["events"]]

        for start in range(0, len(ids), config.TRIAGE_BATCH_SIZE):
            if not self.llm_allowed():
                break
            batch = [NewsItem.from_dict(inbox[i]["item"]) for i in ids[start:start + config.TRIAGE_BATCH_SIZE]]
            try:
                results = triage(llm, batch, recent)
                self.st.bump("llm_calls")
                self.llm_ok = True
            except LLMError as e:
                self.st.bump("llm_errors")
                self.llm_error = str(e)
                log.error("сортировка не удалась, продолжу в следующий запуск: %s", e)
                for item in batch:
                    inbox[item.id]["tries"] += 1
                break

            batch.sort(key=lambda it: -results.get(it.id, {}).get("importance", 0))
            for item in batch:
                result = results.get(item.id)
                if result is None:
                    inbox[item.id]["tries"] += 1
                    continue
                del inbox[item.id]
                self.st.bump("triaged")
                item.importance, item.league, item.event = result["importance"], result["league"], result["event"]
                verdict = self._select(item, result, recent)
                self.triage_log.append((item, result["relevant"], verdict))

    def _select(self, item: NewsItem, result: dict, recent: list[str]) -> str:
        if not result["relevant"]:
            self.st.bump("off_topic")
            return "не по теме"
        threshold = config.IMPORTANCE_MIN if item.league in config.MAIN_LEAGUES else config.IMPORTANCE_MIN_OTHER
        if item.importance < threshold:
            self.st.bump("below_threshold")
            return f"ниже порога {threshold}"
        if result["duplicate"] or is_duplicate(item.event, recent):
            self.st.bump("duplicates")
            return "дубль"
        recent.append(item.event)
        self.st.data["events"].append({"event": item.event, "id": item.id, "ts": ts()})
        self.st.data["pending"][item.id] = {"item": item.to_dict(), "added": ts(), "tries": 0}
        self.st.bump("selected")
        return "ОТОБРАНО"

    def summarize_pending(self, llm: LLM) -> None:
        d = self.st.data
        pending = d["pending"]
        self.st.bump("expired", _drop_stale(pending, config.PENDING_TTL_HOURS))

        budget = min(config.MAX_SUMMARIES_PER_RUN, config.MAX_CARDS_PER_DAY - self.st.daily["cards"])
        if config.auto_publish_now():
            budget = min(budget, config.MAX_POSTS_PER_DAY - self.st.daily["published"] - len(d["approved"]))
            if config.MAX_POSTS_PER_HOUR:
                budget = min(budget, config.MAX_POSTS_PER_HOUR - published_last_hour(d) - len(d["approved"]))
        if self.dry_run:
            budget = min(budget, 5)
        ids = sorted(pending, key=lambda i: -pending[i]["item"]["importance"])[: max(budget, 0)]

        for item_id in ids:
            if not self.llm_allowed():
                break
            item = NewsItem.from_dict(pending[item_id]["item"])
            article = extract.fetch_article(item.url)
            text = article.text
            item.image_url = article.image_url or item.image_url
            try:
                result = summarize(llm, item, text)
                self.st.bump("llm_calls")
                self.llm_ok = True
            except LLMError as e:
                self.st.bump("llm_errors")
                self.llm_error = str(e)
                pending[item_id]["tries"] += 1
                log.error("пересказ не удался, продолжу в следующий запуск: %s", e)
                break

            item.title_ru, item.summary_ru, item.category = result["title_ru"], result["summary_ru"], result["category"]
            del pending[item_id]
            self.st.bump("summarized")

            if self.dry_run:
                print("\n" + "─" * 70)
                print(f"[{item.importance}/10 · {item.league} · {item.source}] {'текст статьи' if text else 'только анонс'}"
                      f" · картинка: {item.image_url or 'нет'}")
                print(publish.post_text(item))
                continue

            auto = config.auto_publish_now() or (
                config.AUTO_PUBLISH_THRESHOLD and item.importance >= config.AUTO_PUBLISH_THRESHOLD)
            if auto:
                d["cards"][item_id] = moderation.new_card(item, None, "approved")
                d["approved"].append(item_id)
            else:
                message_id, is_photo = moderation.send_card(self.tg, item)
                d["cards"][item_id] = moderation.new_card(item, message_id, "sent", photo=is_photo)
                self.st.bump("cards")
            self.st.save()


    def print_triage(self) -> None:
        print("\n" + "═" * 70)
        print(f"Сортировка: {len(self.triage_log)} новостей")
        print("═" * 70)
        for item, relevant, verdict in sorted(self.triage_log, key=lambda r: -r[0].importance):
            mark = "►" if verdict == "ОТОБРАНО" else " "
            print(f"{mark} {item.importance:>2} {item.league:<10} {verdict:<16} {item.source:<14} {item.title[:70]}")
            print(f"{'':32}event: {item.event}")


def _drop_stale(queue: dict, ttl_hours: int) -> int:
    expired = 0
    for item_id, entry in list(queue.items()):
        if entry["tries"] >= config.MAX_LLM_TRIES:
            del queue[item_id]
        elif age_hours(entry["added"]) > ttl_hours:
            del queue[item_id]
            expired += 1
    return expired


def daily_report(day: dict, disabled_feeds: list[str]) -> str:
    lines = [
        f"📊 Сводка за {day['date']}",
        f"Собрано новых: {day['collected']}",
        f"Отсортировано: {day['triaged']} · отобрано: {day['selected']}",
        f"Отсеяно: не по теме {day.get('off_topic', 0)} · ниже порога {day.get('below_threshold', 0)}"
        f" · дубли {day.get('duplicates', 0)}",
        f"Пересказано: {day['summarized']} · карточек: {day['cards']}",
        f"Опубликовано новостей: {day['published']} · отклонено: {day['rejected']}",
        f"Результатов матчей: {day['results']}",
        f"Запросов к LLM: {day['llm_calls']} · ошибок: {day['llm_errors']}",
    ]
    if disabled_feeds:
        lines.append("Отключённые ленты: " + ", ".join(disabled_feeds))
    return "\n".join(lines)
