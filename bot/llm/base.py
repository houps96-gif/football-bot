from typing import Protocol

from bot import config


class LLMError(Exception):
    pass


class LLM(Protocol):
    name: str

    def generate_json(self, system: str, user: str, schema: dict, max_tokens: int) -> dict: ...


TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "relevant": {"type": "boolean"},
                    "importance": {"type": "integer"},
                    "league": {"type": "string", "enum": config.LEAGUES},
                    "event": {"type": "string"},
                    "topic": {"type": "string"},
                    "duplicate": {"type": "boolean"},
                },
                "required": ["id", "relevant", "importance", "league", "event", "topic", "duplicate"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title_ru": {"type": "string"},
        "summary_ru": {"type": "string"},
        "category": {"type": "string", "enum": config.CATEGORIES},
    },
    "required": ["title_ru", "summary_ru", "category"],
    "additionalProperties": False,
}


def get_llm() -> LLM:
    if config.LLM_PROVIDER == "gemini":
        from bot.llm.gemini import GeminiLLM
        return GeminiLLM(config.GEMINI_API_KEY, config.GEMINI_MODELS)
    if config.LLM_PROVIDER == "claude":
        from bot.llm.claude import ClaudeLLM
        return ClaudeLLM(config.ANTHROPIC_API_KEY, config.CLAUDE_MODEL)
    raise SystemExit(f"Неизвестный LLM_PROVIDER={config.LLM_PROVIDER!r}: ожидается gemini или claude")
