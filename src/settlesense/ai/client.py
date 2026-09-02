"""AI client wrapper — the failure gate (ADR-005).

The whole AI layer talks to exactly one method: `parse(system, user, model)`.
That is why swapping providers touches this file and nothing else — the
grounding gate, template fallback, cache and orchestration never learn which
model answered.

Three properties this file exists to guarantee:

  1. **No key, no problem.** The client is built lazily and reports
     `available() == False` with no credentials. Nothing raises at import time,
     so the application runs unchanged without a key.
  2. **Bounded latency.** Per-call timeout, one retry, and a circuit breaker
     that stops calling after N consecutive failures in a run.
  3. **Failures are values, not exceptions.** Every call returns `None` on
     failure and the caller falls back to a template. Totals never depend on it.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from settlesense.contracts.config import AIConfig

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Gemini rejects deadlines below this with a 400 INVALID_ARGUMENT.
GEMINI_MIN_TIMEOUT_S = 10

# Env var checked per provider, in order.
KEY_ENV_VARS = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
}


@dataclass
class CallStats:
    throttled_seconds: float = 0.0
    calls: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    circuit_open: bool = False
    last_error: str | None = None
    reasons: list[str] = field(default_factory=list)


class AIClient:
    """Structured-output calls to Gemini or Claude, or a graceful nothing."""

    def __init__(self, config: AIConfig, api_key: str | None = None) -> None:
        self.config = config
        self.provider = config.provider.lower()
        self._api_key = (api_key or self._key_from_env() or "").strip() or None
        self._client: Any = None
        self._init_failed = False
        self._last_call_at = 0.0
        self.stats = CallStats()

    def _key_from_env(self) -> str | None:
        for name in KEY_ENV_VARS.get(self.provider, ()):
            value = os.environ.get(name)
            if value and value.strip():
                return value
        return None

    # -- availability --------------------------------------------------------

    def available(self) -> bool:
        """True when a real call could be made. False is a normal state: the
        engine's numbers do not depend on it."""
        if self._init_failed or not self._api_key or self.stats.circuit_open:
            return False
        return self._ensure_client() is not None

    def unavailable_reason(self) -> str | None:
        if self._api_key is None:
            names = " or ".join(KEY_ENV_VARS.get(self.provider, ("<unknown>",)))
            return f"{names} is not set"
        if self._init_failed:
            return self.stats.last_error or "client could not be constructed"
        if self.stats.circuit_open:
            return (
                f"circuit breaker open after "
                f"{self.config.circuit_breaker_failures} consecutive failures"
            )
        return None

    def _ensure_client(self) -> Any:
        if self._client is not None or self._init_failed:
            return self._client
        try:
            if self.provider == "gemini":
                from google import genai
                from google.genai import types

                self._client = genai.Client(
                    api_key=self._api_key,
                    # HttpOptions.timeout is milliseconds. Gemini rejects any
                    # deadline under 10s with a 400, so clamp rather than let
                    # a config value silently turn every case into a template.
                    http_options=types.HttpOptions(
                        timeout=max(self.config.timeout_seconds, GEMINI_MIN_TIMEOUT_S)
                        * 1000
                    ),
                )
            elif self.provider == "anthropic":
                import anthropic

                self._client = anthropic.Anthropic(
                    api_key=self._api_key,
                    timeout=float(self.config.timeout_seconds),
                )
            else:
                raise ValueError(f"unknown ai.provider: {self.config.provider!r}")
        except Exception as exc:  # missing SDK, bad key shape, bad provider
            log.warning("AI client unavailable: %s", exc)
            self._init_failed = True
            self.stats.last_error = f"{type(exc).__name__}: {exc}"
        return self._client

    # -- calls ---------------------------------------------------------------

    def parse(self, system: str, user: str, output_model: type[T]) -> T | None:
        """One structured-output call. Returns None on any failure."""
        if self.stats.circuit_open or not self.available():
            return None

        attempts = self.config.max_retries + 1
        for attempt in range(attempts):
            try:
                self._throttle()
                self.stats.calls += 1
                parsed = (
                    self._parse_gemini(system, user, output_model)
                    if self.provider == "gemini"
                    else self._parse_anthropic(system, user, output_model)
                )
                if parsed is None:
                    return self._fail("model returned no parsable output")
                self.stats.consecutive_failures = 0
                return parsed
            except Exception as exc:
                if self._is_retryable(exc) and attempt < attempts - 1:
                    # Backoff is not optional on a rate limit: retrying
                    # immediately is guaranteed to hit the same limit again,
                    # which burns the retry budget and trips the circuit
                    # breaker on a service that was merely busy.
                    delay = self.config.retry_backoff_seconds * (2**attempt)
                    log.info(
                        "AI call failed (%s), retrying in %.1fs",
                        type(exc).__name__,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                return self._fail(f"{type(exc).__name__}: {exc}")
        return None

    def _throttle(self) -> None:
        """Keep a minimum gap between calls so a free-tier per-minute quota is
        paced rather than exhausted in the first few seconds."""
        gap = self.config.min_interval_seconds
        if gap <= 0:
            return
        wait = gap - (time.monotonic() - self._last_call_at)
        if wait > 0:
            self.stats.throttled_seconds += wait
            time.sleep(wait)
        self._last_call_at = time.monotonic()

    def _parse_gemini(self, system: str, user: str, output_model: type[T]) -> T | None:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self.config.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=output_model,
                max_output_tokens=self.config.max_tokens,
                # Explanation is a low-reasoning task on a tight latency
                # budget; thinking would routinely blow the timeout.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                # A Pydantic response_schema otherwise trips the SDK's
                # automatic-function-calling path, which logs a warning on
                # every single call. We never call tools here.
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )
        parsed = response.parsed
        if isinstance(parsed, output_model):
            return parsed
        # `parsed` is None when the model returned prose or malformed JSON.
        # Fall back to validating the raw text before giving up.
        if response.text:
            try:
                return output_model.model_validate_json(response.text)
            except ValidationError:
                return None
        return None

    def _parse_anthropic(
        self, system: str, user: str, output_model: type[T]
    ) -> T | None:
        response = self._client.messages.parse(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            output_format=output_model,
            output_config={"effort": self.config.effort},
            system=[
                {
                    "type": "text",
                    "text": system,
                    # Identical for every case in a run, so caching it makes
                    # the batch materially cheaper and faster.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
        if getattr(response, "stop_reason", None) == "refusal":
            return None
        return response.parsed_output

    def _is_retryable(self, exc: Exception) -> bool:
        """Timeouts, rate limits and 5xx are worth one more attempt; a 400 or
        an auth failure is not."""
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return True

        if self.provider == "gemini":
            try:
                from google.genai import errors
            except ImportError:
                return False
            if isinstance(exc, errors.ServerError):
                return True
            if isinstance(exc, errors.ClientError):
                return getattr(exc, "code", 0) == 429  # rate limited
            return False

        try:
            import anthropic
        except ImportError:
            return False
        if isinstance(
            exc,
            (
                anthropic.APITimeoutError,
                anthropic.RateLimitError,
                anthropic.APIConnectionError,
            ),
        ):
            return True
        if isinstance(exc, anthropic.APIStatusError):
            return exc.status_code >= 500
        return False

    def _fail(self, reason: str) -> None:
        self.stats.failures += 1
        self.stats.consecutive_failures += 1
        self.stats.last_error = reason
        self.stats.reasons.append(reason)
        if self.stats.consecutive_failures >= self.config.circuit_breaker_failures:
            self.stats.circuit_open = True
            log.warning(
                "AI circuit breaker opened after %d consecutive failures; "
                "remaining cases will use template explanations",
                self.stats.consecutive_failures,
            )
        return None
