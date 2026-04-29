from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Listing:
    listing_id: str
    source: str
    city: str
    district: str
    community: str
    title: str
    layout: str
    area_sqm: float
    total_price_wan: float
    listed_at: str
    url: str
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Listing":
        return cls(**payload)

    @property
    def unit_price_yuan(self) -> int:
        if self.area_sqm <= 0:
            return 0
        return int(self.total_price_wan * 10000 / self.area_sqm)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

