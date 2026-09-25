import json
import logging

import anthropic

from bot.llm.base import LLMError

log = logging.getLogger(__name__)


class ClaudeLLM:
    name = "claude"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise SystemExit("ANTHROPIC_API_KEY не задан")
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=60)

    def generate_json(self, system: str, user: str, schema: dict, max_tokens: int) -> dict:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIConnectionError as e:
            raise LLMError(f"claude: нет соединения: {e}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"claude: HTTP {e.status_code}: {e.message}") from e

        if response.stop_reason != "end_turn":
            raise LLMError(f"claude: stop_reason={response.stop_reason}")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"claude: ответ не JSON: {text[:200]}") from e
        log.info("claude %s: %s", self.model, response.usage)
        return result
