from __future__ import annotations

from .anjuke import AnjukeCollector
from .base import BaseCollector
from .beike import BeikeCollector
from .lianjia import LianjiaCollector


_REGISTRY: dict[str, type[BaseCollector]] = {
    "beike": BeikeCollector,
    "lianjia": LianjiaCollector,
    "anjuke": AnjukeCollector,
}


def create_collector(source_name: str) -> BaseCollector:
    collector_cls = _REGISTRY.get(source_name.lower())
    if collector_cls is None:
        raise ValueError(f"不支持的数据源: {source_name}")
    return collector_cls()

