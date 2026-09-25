import json
import logging
import time

import httpx2 as httpx

from bot import config
from bot.llm.base import LLMError

log = logging.getLogger(__name__)

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SKIP_MODEL = {404, 429, 500, 502, 503, 504}
ROUNDS = 2
ROUND_PAUSE_SECONDS = 5


def _without_additional_properties(schema):
    if isinstance(schema, dict):
        return {k: _without_additional_properties(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [_without_additional_properties(v) for v in schema]
    return schema


class GeminiLLM:
    name = "gemini"

    def __init__(self, api_key: str, models: list[str], timeout: float = 45):
        if not api_key:
            raise SystemExit("GEMINI_API_KEY не задан")
        self.models = models
        self.client = httpx.Client(timeout=timeout, headers={"X-goog-api-key": api_key})
        self._last_request = 0.0

    def _post(self, model: str, body: dict):
        wait = self._last_request + config.LLM_MIN_INTERVAL_SECONDS - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return self.client.post(API_URL.format(model=model), json=body)
        finally:
            self._last_request = time.monotonic()

    def generate_json(self, system: str, user: str, schema: dict, max_tokens: int) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": _without_additional_properties(schema),
                "maxOutputTokens": max_tokens,
                "temperature": 0.3,
            },
        }
        errors = []
        for round_no in range(ROUNDS):
            for model in self.models:
                try:
                    response = self._post(model, body)
                except httpx.TransportError as e:
                    errors.append(f"{model}: {type(e).__name__}")
                    continue
                if response.status_code in SKIP_MODEL:
                    errors.append(f"{model}: HTTP {response.status_code}")
                    continue
                if response.status_code != 200:
                    raise LLMError(f"{model}: HTTP {response.status_code} {response.text[:300]}")
                return self._parse(model, response.json())
            if round_no + 1 < ROUNDS:
                time.sleep(ROUND_PAUSE_SECONDS)
        raise LLMError("все модели Gemini недоступны: " + "; ".join(errors))

    @staticmethod
    def _parse(model: str, data: dict) -> dict:
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError(f"{model}: пустой ответ {data.get('promptFeedback')}")
        candidate = candidates[0]
        if candidate.get("finishReason") not in (None, "STOP"):
            raise LLMError(f"{model}: ответ оборван, finishReason={candidate.get('finishReason')}")
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"{model}: ответ не JSON: {text[:200]}") from e
        log.info("gemini %s: %s", model, data.get("usageMetadata"))
        return result
