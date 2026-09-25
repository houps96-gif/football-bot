import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LLM_MIN_INTERVAL_SECONDS", "10")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import httpx2 as httpx

from bot import config, results
from bot.llm import LLMError, get_llm

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}"
CLUB_LEAGUES = ["eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "por.1"]
NATIONAL_SOURCES = ["fifa.world", "uefa.nations", "fifa.friendly", "conmebol.america", "concacaf.gold"]
BATCH = 80


def get(client: httpx.Client, url: str) -> dict:
    try:
        response = client.get(url)
        return response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}


def collect_names() -> set[str]:
    names: set[str] = set()
    with httpx.Client(timeout=20) as client:
        club_league = {}
        for slug in CLUB_LEAGUES:
            data = get(client, BASE.format(slug=slug) + "/teams")
            for t in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
                names.add(t["team"]["displayName"])
                club_league[int(t["team"]["id"])] = slug

        for team_id, title in config.TOP_TEAMS.items():
            sources = [club_league[team_id]] if team_id in club_league else NATIONAL_SOURCES
            players = set()
            for slug in sources:
                data = get(client, BASE.format(slug=slug) + f"/teams/{team_id}/roster")
                players |= {a["displayName"] for a in data.get("athletes", []) if a.get("displayName")}
            names |= players | {title}
            print(f"{title:22} игроков: {len(players)}")
    return names


def main() -> None:
    path = config.NAMES_PATH
    known = json.loads(path.read_text("utf-8")) if path.exists() else {}
    names = collect_names()
    missing = results.missing_names(names, known)
    print(f"\nвсего имён: {len(names)}, уже в словаре: {len(names) - len(missing)}, перевести: {len(missing)}")

    llm = get_llm()
    for start in range(0, len(missing), BATCH):
        batch = set(missing[start:start + BATCH])
        try:
            results.translate(llm, batch, known)
        except LLMError as e:
            print(f"пачка {start // BATCH + 1}: не перевелась ({e}) — запустите скрипт ещё раз позже")
            continue
        path.write_text(json.dumps(dict(sorted(known.items())), ensure_ascii=False, indent=1), "utf-8")
        print(f"пачка {start // BATCH + 1}/{-(-len(missing) // BATCH)}: в словаре {len(known)}")

    left = results.missing_names(names, known)
    print(f"\nготово: в словаре {len(known)} имён, не переведено {len(left)}")


if __name__ == "__main__":
    main()
