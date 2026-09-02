from __future__ import annotations

import pytest

from settlesense.contracts.config import MatchingConfig


@pytest.fixture
def config() -> MatchingConfig:
    return MatchingConfig(
        tolerance_paise=100, settlement_window_days=2, score_epsilon=0.01
    )
