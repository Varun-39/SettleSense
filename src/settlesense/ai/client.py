"""Anthropic client wrapper — the failure gate (ADR-005).

Three properties this file exists to guarantee:

  1. **No key, no problem.** The client is constructed lazily and reports
     `available() == False` when no credentials are present. Nothing raises at
     import time, so the whole application runs unchanged without a key.
  2. **Bounded latency.** Per-call timeout, one retry, and a circuit breaker
     that stops calling after N consecutive failures in a run.
  3. **Failures are values, not exceptions.** Every call returns `None` on
     failure. The caller falls back to a template; totals never depend on this.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from settlesense.contracts.config import AIConfig

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class CallStats:
    calls: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    circuit_open: bool = False
    last_error: str | None = None
    reasons: list[str] = field(default_factory=list)


class AIClient:
    """Structured-output calls to Claude, or a graceful nothing."""

    def __init__(self, config: AIConfig, api_key: str | None = None) -> None:
        self.config = config
        # An empty or whitespace-only env var is "no key", not a key that will
        # fail later with a confusing auth error.
        raw_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or ""
        self._api_key = raw_key.strip() or None
        self._client: Any = None
        self._init_failed = False
        self.stats = CallStats()

    # -- availability --------------------------------------------------------

    def available(self) -> bool:
        """True when a real call could be made. False is a normal state: the
        engine's numbers do not depend on it."""
        if self._init_failed or not self._api_key:
            return False
        return self._ensure_client() is not None

    def _ensure_client(self) -> Any:
        if self._client is not None or self._init_failed:
            return self._client
        try:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=self._api_key, timeout=float(self.config.timeout_seconds)
            )
        except Exception as exc:  # ImportError, bad key format, ...
            log.warning("AI client unavailable: %s", exc)
            self._init_failed = True
            self.stats.last_error = str(exc)
        return self._client

    def unavailable_reason(self) -> str | None:
        if self._api_key is None:
            return "ANTHROPIC_API_KEY is not set"
        if self._init_failed:
            return self.stats.last_error or "client could not be constructed"
        if self.stats.circuit_open:
            return (
                f"circuit breaker open after "
                f"{self.config.circuit_breaker_failures} consecutive failures"
            )
        return None

    # -- calls ---------------------------------------------------------------

    def parse(
        self, system: str, user: str, output_model: type[T]
    ) -> T | None:
        """One structured-output call. Returns None on any failure."""
        if self.stats.circuit_open or not self.available():
            return None

        client = self._ensure_client()
        attempts = self.config.max_retries + 1

        for attempt in range(attempts):
            try:
                self.stats.calls += 1
                response = client.messages.parse(
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    output_format=output_model,
                    # Effort is held low deliberately: this call sits inside an
                    # 8s budget and the task is explanation, not reasoning.
                    output_config={"effort": self.config.effort},
                    system=[
                        {
                            "type": "text",
                            "text": system,
                            # The system prompt is identical for every case in a
                            # run, so caching it makes the batch materially
                            # cheaper and faster.
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user}],
                )

                if getattr(response, "stop_reason", None) == "refusal":
                    return self._fail("model declined the request")

                parsed = response.parsed_output
                self.stats.consecutive_failures = 0
                return parsed

            except Exception as exc:
                retryable = self._is_retryable(exc)
                if retryable and attempt < attempts - 1:
                    log.info("AI call failed (%s), retrying", type(exc).__name__)
                    continue
                return self._fail(f"{type(exc).__name__}: {exc}")

        return None

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Timeouts, rate limits, connection errors and 5xx are worth one more
        attempt; a 400 or an auth failure is not."""
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
