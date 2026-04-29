from __future__ import annotations

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_listings(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dedup_keys: set[tuple[str, str, str, float, float]] = set()
    cleaned: list[dict[str, Any]] = []

    for row in raw_rows:
        source = str(row.get("source", "")).strip().lower()
        title = str(row.get("title", "")).strip()
        community = str(row.get("community", "")).strip()
        area = round(_safe_float(row.get("area_sqm")), 2)
        total = round(_safe_float(row.get("total_price_wan")), 2)

        if not source or not title or area <= 0 or total <= 0:
            continue

        key = (source, title, community, area, total)
        if key in dedup_keys:
            continue
        dedup_keys.add(key)

        layout = str(row.get("layout", "")).strip() or "未知户型"
        district = str(row.get("district", "")).strip() or "未知区域"
        city = str(row.get("city", "")).strip() or "未知城市"
        tags = row.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]

        unit_price = int(total * 10000 / area)

        cleaned.append(
            {
                "listing_id": str(row.get("listing_id", "")).strip() or f"{source}-{len(cleaned)+1}",
                "source": source,
                "city": city,
                "district": district,
                "community": community,
                "title": title,
                "layout": layout,
                "area_sqm": area,
                "total_price_wan": total,
                "unit_price_yuan": unit_price,
                "listed_at": str(row.get("listed_at", "")).strip(),
                "url": str(row.get("url", "")).strip(),
                "tags": tags,
            }
        )
    return cleaned

