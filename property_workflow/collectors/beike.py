from __future__ import annotations

from typing import Any

from .aplus_desktop import collect_from_aplus_desktop
from .base import BaseCollector
from .synthetic import build_synthetic_listings


class BeikeCollector(BaseCollector):
    source_name = "beike"

    def collect(
        self, city: str, districts: list[str], limit: int, options: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        desktop_options = (options or {}).get("desktop_aplus") or {}
        desktop_enabled = bool(desktop_options.get("enabled", False))
        fallback_to_synthetic = bool(desktop_options.get("fallback_to_synthetic", True))

        if desktop_enabled:
            try:
                rows = collect_from_aplus_desktop(
                    city=city,
                    districts=districts,
                    limit=limit,
                    options=options,
                )
                if rows:
                    return rows
            except Exception as exc:
                print(f"[beike][desktop] collect failed: {exc}")
                if not fallback_to_synthetic:
                    raise
        return build_synthetic_listings(self.source_name, city, districts, limit)
