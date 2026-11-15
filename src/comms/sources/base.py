from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from comms.config import AppConfig
from comms.http import RunBudget
from comms.models import ArtistBundle, Seed
from comms.store.sqlite import SQLiteStore


class SourceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ArtistNotFound(SourceError):
    pass


@dataclass
class SourceContext:
    config: AppConfig
    store: SQLiteStore
    budget: RunBudget

    @property
    def now(self) -> float:
        from comms.timeutil import now_ts

        return now_ts()


class Source(ABC):
    site: str

    def __init__(self, options: Any, config: AppConfig) -> None:
        self.options = options
        self.config = config

    async def open(self, ctx: SourceContext) -> None:
        return None

    async def close(self) -> None:
        return None

    async def discover(self, ctx: SourceContext, limit: int) -> AsyncIterator[Seed]:
        if False:  # pragma: no cover - keeps the abstract iterator shape
            yield Seed(site=self.site, handle="")
        return

    @abstractmethod
    async def fetch(self, ctx: SourceContext, seed: Seed) -> ArtistBundle:
        raise NotImplementedError
