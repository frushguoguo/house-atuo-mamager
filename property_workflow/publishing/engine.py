from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .base import Publisher
from .mock_publishers import (
    DouyinMockPublisher,
    KuaishouMockPublisher,
    WechatVideoMockPublisher,
    XiaohongshuMockPublisher,
)


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _copy_map(copywriting_items: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in copywriting_items:
        if not isinstance(item, dict):
            continue
        listing_id = _safe_text(item.get("listing_id"))
        if not listing_id:
            continue
        variants = item.get("variants")
        if isinstance(variants, list) and variants:
            primary = _safe_text(variants[0])
            if primary:
                result[listing_id] = primary
                continue
        title = _safe_text(item.get("title"))
        if title:
            result[listing_id] = title
    return result


def _hashtags_for_listing(listing: dict[str, Any]) -> list[str]:
    city = _safe_text(listing.get("city"), "city")
    district = _safe_text(listing.get("district"), "district")
    source = _safe_text(listing.get("source"), "listing")
    base_tags = [f"#{city}", f"#{district}", f"#{source}", "#property"]
    deduped: list[str] = []
    seen: set[str] = set()
    for tag in base_tags:
        if tag in seen:
            continue
        seen.add(tag)
        deduped.append(tag)
    return deduped


def _video_asset(video_report: dict[str, Any] | None, run_dir: Path) -> dict[str, Any] | None:
    if not isinstance(video_report, dict):
        return None
    output_video = _safe_text(video_report.get("output_video"))
    if not output_video:
        return None
    video_path = Path(output_video)
    if not video_path.is_absolute():
        video_path = (run_dir / video_path).resolve()
    if not video_path.exists():
        return None
    return {
        "type": "video",
        "path": str(video_path),
        "duration_seconds": video_report.get("duration_seconds"),
    }


def build_publish_bundle(
    clean_rows: list[dict[str, Any]],
    copywriting_items: list[dict[str, Any]] | None = None,
    *,
    video_report: dict[str, Any] | None = None,
    run_dir: Path | None = None,
    top_n: int = 8,
    call_to_action: str = "DM for details and viewing schedule.",
) -> dict[str, Any]:
    rows = clean_rows[: max(1, int(top_n))]
    copy_map = _copy_map(copywriting_items or [])

    items: list[dict[str, Any]] = []
    for row in rows:
        listing_id = _safe_text(row.get("listing_id"), "unknown")
        district = _safe_text(row.get("district"), "district")
        community = _safe_text(row.get("community"), "community")
        layout = _safe_text(row.get("layout"), "layout")
        area = row.get("area_sqm")
        price = row.get("total_price_wan")
        title = _safe_text(row.get("title"), f"{district} {community} {layout}")
        base_copy = copy_map.get(listing_id, title)

        caption = (
            f"{base_copy}\n"
            f"Area: {area} sqm | Price: {price} wan | Layout: {layout}\n"
            f"{call_to_action}"
        )
        items.append(
            {
                "listing_id": listing_id,
                "title": title,
                "caption": caption,
                "hashtags": _hashtags_for_listing(row),
                "url": row.get("url"),
                "district": district,
                "community": community,
            }
        )

    assets: list[dict[str, Any]] = []
    if run_dir is not None:
        video_asset = _video_asset(video_report, run_dir=run_dir)
        if video_asset:
            assets.append(video_asset)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "item_count": len(items),
        "items": items,
        "assets": assets,
    }


def _create_publisher(name: str, settings: dict[str, Any] | None = None) -> Publisher:
    key = _safe_text(name).lower()
    if key == "douyin":
        return DouyinMockPublisher(settings=settings)
    if key == "xiaohongshu":
        return XiaohongshuMockPublisher(settings=settings)
    if key == "kuaishou":
        return KuaishouMockPublisher(settings=settings)
    if key in {"wechat_video", "video_channel"}:
        return WechatVideoMockPublisher(settings=settings)
    raise ValueError(f"unsupported publish platform: {name}")


def publish_to_enabled_platforms(
    config: dict[str, Any],
    bundle: dict[str, Any],
    *,
    run_dir: Path,
) -> dict[str, Any]:
    platform_defs = config.get("publish_platforms", [])
    enabled_defs = []
    for row in platform_defs:
        if not isinstance(row, dict):
            continue
        if bool(row.get("enabled", False)):
            enabled_defs.append(row)

    if not enabled_defs:
        return {
            "status": "skipped_no_enabled_platforms",
            "enabled_platforms": [],
            "results": [],
            "total_posts": int(bundle.get("item_count", 0)),
        }

    results: list[dict[str, Any]] = []
    for row in enabled_defs:
        name = _safe_text(row.get("name"))
        if not name:
            continue
        try:
            publisher = _create_publisher(name, settings=row)
            result = publisher.publish(bundle, run_dir)
        except Exception as exc:  # pragma: no cover - guard rail
            result = {
                "platform": name,
                "status": "failed",
                "published_count": 0,
                "error": str(exc),
            }
        results.append(result)

    success_count = sum(1 for row in results if row.get("status") == "success")
    failed_count = len(results) - success_count
    if success_count == len(results):
        status = "success"
    elif success_count > 0:
        status = "partial_success"
    else:
        status = "failed"

    return {
        "status": status,
        "enabled_platforms": [_safe_text(row.get("name")) for row in enabled_defs],
        "results": results,
        "total_posts": int(bundle.get("item_count", 0)),
        "success_platform_count": success_count,
        "failed_platform_count": failed_count,
    }

