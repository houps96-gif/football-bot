import importlib
from types import ModuleType


def load(name: str) -> ModuleType:
    try:
        return importlib.import_module(f"bot.profiles.{name}")
    except ModuleNotFoundError as e:
        raise SystemExit(f"Нет профиля канала {name!r} (bot/profiles/{name}.py)") from e
