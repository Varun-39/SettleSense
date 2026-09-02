"""Loads recon.config.yaml. No numeric literal for a tolerance, window, or
threshold should exist anywhere in rule code — see ADR-002/ADR-004.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class MatchingConfig(BaseModel):
    tolerance_paise: int
    settlement_window_days: int
    score_epsilon: float


class AIConfig(BaseModel):
    model: str
    effort: str = "low"
    max_tokens: int
    timeout_seconds: int
    max_retries: int
    circuit_breaker_failures: int
    prompt_version: str


class CurrencyConfig(BaseModel):
    supported: list[str]


class EngineConfig(BaseModel):
    matching: MatchingConfig
    ai: AIConfig
    currency: CurrencyConfig


def load_config(path: str | Path = "recon.config.yaml") -> EngineConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return EngineConfig.model_validate(raw)
