import html
import json
from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from bot import config, glossary
from bot.llm import LLM
from bot.sources.matches import Goal, Match

NAMES_SCHEMA = {
    "type": "object",
    "properties": {
        "names": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"src": {"type": "string"}, "ru": {"type": "string"}},
                "required": ["src", "ru"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["names"],
    "additionalProperties": False,
}

NAMES_SYSTEM = """Переведи названия футбольных команд и имена игроков на русский так, как их пишут русскоязычные спортивные СМИ в протоколе матча.

- Команды — без кавычек, в привычной форме: Arsenal — Арсенал, Bayern Munich — Бавария, Internazionale — Интер, AS Roma — Рома, Borussia Dortmund — Боруссия Д, Tottenham Hotspur — Тоттенхэм, Manchester City — Манчестер Сити. Сборные — по-русски: England — Англия, Netherlands — Нидерланды.
- Игроки — только фамилия, как в протоколе: Bukayo Saka — Сака, Virgil van Dijk — ван Дейк, Kevin De Bruyne — Де Брёйне. Если игрока принято звать по имени или прозвищу — так и пиши: Vinícius Júnior — Винисиус, Rodri — Родри, Pedri — Педри.
- Если в запросе есть «Глоссарий» — используй написания оттуда (для протокола — только фамилию).

Верни по одному элементу на каждое имя из списка, поле src — ровно как в запросе."""


def match_names(matches: list[Match], players: bool = True) -> set[str]:
    names = set()
    for m in matches:
        names |= {m.home, m.away}
        if players:
            names |= {g.player for g in m.goals + m.red_cards if g.player}
    return names


@lru_cache(maxsize=1)
def prefilled() -> dict[str, str]:
    path = config.NAMES_PATH
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def lookup(names: set[str], cache: dict[str, str]) -> dict[str, str]:
    known = prefilled()
    return {n: cache.get(n) or known[n] for n in names if n in cache or n in known}


def missing_names(names: set[str], cache: dict[str, str]) -> list[str]:
    known = prefilled()
    return sorted(n for n in names if n and n not in cache and n not in known)


def translate(llm: LLM, names: set[str], cache: dict[str, str]) -> dict[str, str]:
    missing = missing_names(names, cache)
    if missing:
        hints = glossary.hits(" ; ".join(missing))
        prompt = ("Глоссарий:\n" + "\n".join(hints) + "\n\n" if hints else "") + "Имена:\n" + "\n".join(missing)
        result = llm.generate_json(NAMES_SYSTEM, prompt, NAMES_SCHEMA, max_tokens=4096)
        for row in result.get("names", []):
            if row.get("src") in missing and row.get("ru"):
                cache[row["src"]] = row["ru"].strip()
    return lookup(names, cache)


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _score(m: Match) -> str:
    score = f"{m.home_score}:{m.away_score}"
    if m.home_pens is not None and m.away_pens is not None:
        score += f" (пен. {m.home_pens}:{m.away_pens})"
    return score


def _goal(g: Goal, ru: dict[str, str]) -> str:
    text = f"{_esc(ru.get(g.player, g.player))} {g.minute}"
    if g.penalty:
        text += " (пен.)"
    if g.own_goal:
        text += " (автогол)"
    return text


def goal_lines(m: Match, ru: dict[str, str]) -> list[str]:
    home, away = ru.get(m.home, m.home), ru.get(m.away, m.away)
    complete = (sum(g.side == "home" for g in m.goals) == m.home_score
                and sum(g.side == "away" for g in m.goals) == m.away_score)
    if not m.goals and m.home_score == m.away_score == 0:
        return ["Без голов."]
    if not complete:
        return []
    lines = []
    for side, name in (("home", home), ("away", away)):
        goals = [_goal(g, ru) for g in m.goals if g.side == side]
        if goals:
            lines.append(f"{_esc(name)}: " + ", ".join(goals))
    return lines


def post_text(m: Match, ru: dict[str, str]) -> str:
    home, away = ru.get(m.home, m.home), ru.get(m.away, m.away)
    lines = [f"<b>{_esc(home)} — {_esc(away)} {_score(m)}</b>", _esc(m.competition), ""]
    lines += goal_lines(m, ru)
    if m.red_cards:
        reds = [f"{_esc(ru.get(r.player, r.player))} {r.minute} ({_esc(home if r.side == 'home' else away)})" for r in m.red_cards]
        lines.append("Удаления: " + ", ".join(reds))
    footer = f'<a href="{html.escape(m.url, quote=True)}">Протокол матча</a>' if m.url else ""
    tag = f"#{m.tag}"
    lines += ["", f"{footer} · {tag}" if footer else tag]
    text = "\n".join(lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


W, H = 1280, 720
BG_INNER, BG_OUTER = (27, 45, 87), (10, 19, 48)
ACCENT = (230, 57, 70)
MUTED = (201, 214, 242)


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(config.FONTS_DIR / name), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, name: str, size: int, max_width: int) -> ImageFont.FreeTypeFont:
    font = _font(name, size)
    while size > 28 and draw.textlength(text, font=font) > max_width:
        size -= 4
        font = _font(name, size)
    return font


def _center(draw, cx, y, text, font, fill):
    width = draw.textlength(text, font=font)
    top = draw.textbbox((0, 0), text, font=font)[1]
    draw.text((cx - width / 2, y - top), text, font=font, fill=fill)


def _background() -> Image.Image:
    gradient = Image.radial_gradient("L").resize((W, W)).crop((0, (W - H) // 2, W, (W + H) // 2))
    return Image.composite(Image.new("RGB", (W, H), BG_OUTER), Image.new("RGB", (W, H), BG_INNER), gradient)


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def title_card(label: str, title: str) -> bytes:
    img = _background()
    d = ImageDraw.Draw(img)
    _center(d, W / 2, 70, label.upper(), _font("PT_Sans-Web-Bold.ttf", 40), MUTED)
    d.rounded_rectangle((W / 2 - 70, 132, W / 2 + 70, 140), radius=4, fill=ACCENT)

    for size in (84, 76, 68, 60, 52):
        font = _font("PT_Sans-Narrow-Web-Bold.ttf", size)
        lines = _wrap(d, title, font, W - 160)
        if len(lines) <= 4:
            break
    lines = lines[:4]
    step = int(size * 1.15)
    top = 200 + (380 - step * len(lines)) / 2
    for i, line in enumerate(lines):
        _center(d, W / 2, top + i * step, line, font, "white")

    _center(d, W / 2, 640, config.CHANNEL_TITLE.upper(), _font("PT_Sans-Web-Bold.ttf", 30), MUTED)
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def scoreboard(m: Match, ru: dict[str, str]) -> bytes:
    img = _background()
    d = ImageDraw.Draw(img)

    _center(d, W / 2, 70, m.competition.upper(), _font("PT_Sans-Web-Bold.ttf", 40), MUTED)
    d.rounded_rectangle((W / 2 - 70, 132, W / 2 + 70, 140), radius=4, fill=ACCENT)

    home, away = ru.get(m.home, m.home).upper(), ru.get(m.away, m.away).upper()
    for cx, name in ((W * 0.2, home), (W * 0.8, away)):
        font = _fit(d, name, "PT_Sans-Narrow-Web-Bold.ttf", 76, int(W * 0.31))
        _center(d, cx, 300, name, font, "white")

    _center(d, W / 2, 250, f"{m.home_score}:{m.away_score}", _font("PT_Sans-Narrow-Web-Bold.ttf", 190), "white")
    if m.home_pens is not None and m.away_pens is not None:
        _center(d, W / 2, 470, f"пенальти {m.home_pens}:{m.away_pens}", _font("PT_Sans-Web-Bold.ttf", 40), MUTED)

    _center(d, W / 2, 640, config.CHANNEL_TITLE.upper(), _font("PT_Sans-Web-Bold.ttf", 30), MUTED)

    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
