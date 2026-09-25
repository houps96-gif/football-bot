from rapidfuzz import fuzz

from bot import config


def is_duplicate(event: str, known_events: list[str]) -> bool:
    event = event.lower()
    return any(fuzz.token_set_ratio(event, known.lower()) > config.DUP_THRESHOLD for known in known_events)
