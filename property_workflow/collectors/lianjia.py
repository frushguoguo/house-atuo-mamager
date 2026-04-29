from __future__ import annotations

from typing import Any

from .base import BaseCollector
from .synthetic import build_synthetic_listings


class LianjiaCollector(BaseCollector):
    source_name = "lianjia"

    def collect(
        self, city: str, districts: list[str], limit: int, options: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return build_synthetic_listings(self.source_name, city, districts, limit)

