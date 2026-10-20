"""Gemini wrapper: JSON mode, pydantic validation, retries, and disk cache."""
from __future__ import annotations

import hashlib
import json
import logging
import time
import threading
from pathlib import Path
from typing import Any, Type, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from learnloop.config import CACHE_DIR, Settings

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def _is_retryable(exc: BaseException) -> bool:
    """Retry on rate-limit (429) and server errors (5xx)."""
    exc_str = str(exc).lower()
    return "429" in exc_str or "resource exhausted" in exc_str or "500" in exc_str or "503" in exc_str


class LLMStats:
    """Thread-safe counters for API calls and cache hits."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.api_calls = 0
        self.cache_hits = 0

    def inc_api(self) -> None:
        with self._lock:
            self.api_calls += 1

    def inc_cache(self) -> None:
        with self._lock:
            self.cache_hits += 1


stats = LLMStats()


class GeminiLLM:
    """Thin wrapper around google-genai with caching and retries."""

    def __init__(self, settings: Settings) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._settings = settings
        self._semaphore = threading.Semaphore(settings.llm_concurrency)
        self._delay = settings.llm_delay_ms / 1000.0

    # ── cache helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _cache_key(model: str, prompt: str, config_json: str) -> str:
        blob = f"{model}|{prompt}|{config_json}"
        return hashlib.sha256(blob.encode()).hexdigest()

    @staticmethod
    def _cache_path(key: str) -> Path:
        return CACHE_DIR / f"{key}.json"

    def _read_cache(self, key: str) -> str | None:
        p = self._cache_path(key)
        if p.exists():
            stats.inc_cache()
            return p.read_text()
        return None

    def _write_cache(self, key: str, text: str) -> None:
        self._cache_path(key).write_text(text)

    # ── core generate ───────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _call_api(self, model: str, prompt: str, config: types.GenerateContentConfig) -> str:
        """Make the actual Gemini API call with rate-limit retries."""
        self._semaphore.acquire()
        try:
            time.sleep(self._delay)
            resp = self._client.models.generate_content(
                model=model, contents=prompt, config=config,
            )
            stats.inc_api()
            return resp.text or ""
        finally:
            self._semaphore.release()

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        system_instruction: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Generate text, with disk cache."""
        model = model or self._settings.gemini_model_reasoning
        config = types.GenerateContentConfig(temperature=temperature)
        if json_mode:
            config.response_mime_type = "application/json"
        if system_instruction:
            config.system_instruction = system_instruction

        config_json = json.dumps({"temperature": temperature, "json": json_mode, "system": system_instruction or ""}, sort_keys=True)
        cache_key = self._cache_key(model, prompt, config_json)
        cached = self._read_cache(cache_key)
        if cached is not None:
            logger.debug("Cache hit for %s", cache_key[:12])
            return cached

        text = self._call_api(model, prompt, config)
        self._write_cache(cache_key, text)
        return text

    def generate_json(
        self,
        prompt: str,
        schema: Type[T] | None = None,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        system_instruction: str | None = None,
        list_mode: bool = False,
    ) -> Any:
        """Generate JSON, optionally validate with pydantic. Retry up to 2x on parse errors."""
        raw = self.generate(
            prompt, model=model, temperature=temperature,
            system_instruction=system_instruction, json_mode=True,
        )

        for attempt in range(3):
            try:
                data = json.loads(raw)
                if schema is not None:
                    if list_mode:
                        if isinstance(data, list):
                            return [schema.model_validate(item) for item in data]
                        elif isinstance(data, dict) and "items" in data:
                            return [schema.model_validate(item) for item in data["items"]]
                        else:
                            raise ValidationError.from_exception_data(
                                title=schema.__name__,
                                line_errors=[],
                            )
                    return schema.model_validate(data)
                return data
            except (json.JSONDecodeError, ValidationError) as e:
                if attempt < 2:
                    logger.warning("JSON parse/validate failed (attempt %d): %s", attempt + 1, e)
                    repair_prompt = (
                        f"The following JSON is invalid or doesn't match the schema. "
                        f"Fix it and return ONLY the corrected JSON.\n\n"
                        f"Error: {e}\n\nOriginal JSON:\n{raw}"
                    )
                    raw = self.generate(
                        repair_prompt, model=model, temperature=0.0,
                        system_instruction="You are a JSON repair tool. Return only valid JSON.",
                        json_mode=True,
                    )
                else:
                    raise
        return data  # unreachable, but satisfies type checker
