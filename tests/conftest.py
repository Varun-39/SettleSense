from __future__ import annotations

import pytest

from settlesense.contracts.config import MatchingConfig


@pytest.fixture
def config() -> MatchingConfig:
    return MatchingConfig(
        tolerance_paise=100, settlement_window_days=2, score_epsilon=0.01
    )


@pytest.fixture
def no_ai_keys(monkeypatch):
    """Clear every provider key so tests never depend on the dev machine's
    environment — and never spend money by accident."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
