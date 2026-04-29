from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class Publisher(ABC):
    """Base interface for platform publishers."""

    def __init__(self, platform: str, settings: dict[str, Any] | None = None) -> None:
        self.platform = platform
        self.settings = settings or {}

    @abstractmethod
    def publish(self, bundle: dict[str, Any], run_dir: Path) -> dict[str, Any]:
        """Publish prepared bundle to one platform."""
