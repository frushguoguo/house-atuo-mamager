from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import Publisher


class LocalMockPublisher(Publisher):
    """Mock publisher that writes local publish records."""

    def publish(self, bundle: dict[str, Any], run_dir: Path) -> dict[str, Any]:
        if bool(self.settings.get("simulate_failure", False)):
            return {
                "platform": self.platform,
                "mode": "local_mock",
                "status": "failed",
                "error": "simulated failure",
                "published_count": 0,
            }

        items = bundle.get("items", [])
        records: list[dict[str, Any]] = []
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        for idx, item in enumerate(items, start=1):
            listing_id = str(item.get("listing_id", "")).strip()
            records.append(
                {
                    "publish_id": f"{self.platform}_{ts}_{idx:03d}",
                    "platform": self.platform,
                    "status": "published",
                    "listing_id": listing_id,
                    "title": item.get("title"),
                    "published_at": datetime.now().isoformat(timespec="seconds"),
                }
            )

        records_path = run_dir / f"publish_records_{self.platform}.json"
        records_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "platform": self.platform,
            "mode": "local_mock",
            "status": "success",
            "published_count": len(records),
            "records_path": str(records_path),
        }


class DouyinMockPublisher(LocalMockPublisher):
    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(platform="douyin", settings=settings)


class XiaohongshuMockPublisher(LocalMockPublisher):
    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(platform="xiaohongshu", settings=settings)


class KuaishouMockPublisher(LocalMockPublisher):
    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(platform="kuaishou", settings=settings)


class WechatVideoMockPublisher(LocalMockPublisher):
    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        super().__init__(platform="wechat_video", settings=settings)

