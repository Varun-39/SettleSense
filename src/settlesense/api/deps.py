"""Application settings and per-request dependencies."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from settlesense.contracts.config import EngineConfig, load_config
from settlesense.store.repository import Repository


class Settings:
    def __init__(self) -> None:
        self.db_path = os.environ.get("SETTLESENSE_DB", "settlesense.db")
        self.config_path = os.environ.get("SETTLESENSE_CONFIG", "recon.config.yaml")
        self.data_dir = Path(os.environ.get("SETTLESENSE_DATA", "data"))

    def config(self) -> EngineConfig:
        return load_config(self.config_path)


settings = Settings()


def get_settings() -> Settings:
    """The process-wide settings.

    Deliberately a single mutable object: one process serves one database, and
    the FastAPI dependency has to reach it without threading configuration
    through every route. Tests reassign its fields, so a test that changes
    them must set every field it depends on rather than inheriting whatever
    the previous module left behind.
    """
    return settings


def get_repository() -> Iterator[Repository]:
    """One SQLite connection per request. sqlite3 connections are not safe to
    share across threads, and FastAPI runs sync endpoints in a threadpool."""
    repo = Repository(settings.db_path)
    try:
        yield repo
    finally:
        repo.close()
