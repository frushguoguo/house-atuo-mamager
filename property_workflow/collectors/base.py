from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseCollector(ABC):
    source_name: str = "unknown"

    @abstractmethod
    def collect(
        self, city: str, districts: list[str], limit: int, options: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

