from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import property_workflow.orchestration.pipeline as pipeline
from property_workflow.content.video_generator import build_video_storyboard


def test_build_video_storyboard_includes_listing_narrative() -> None:
    clean_rows = [
        {
            "listing_id": "H001",
            "district": "pudong",
            "community": "Demo Community",
            "layout": "2-1-1",
            "area_sqm": 89.3,
            "total_price_wan": 420.5,
            "title": "Demo listing title",
        }
    ]
    copy_items = [
        {
            "listing_id": "H001",
            "variants": ["Professional copy variant A", "variant B"],
        }
    ]

    storyboard = build_video_storyboard(clean_rows, copy_items, template="default", max_items=3)
    shots = storyboard.get("shots", [])
    listing_shots = [row for row in shots if isinstance(row, dict) and row.get("type") == "listing"]

    assert storyboard["generated_item_count"] == 1
    assert len(listing_shots) == 1
    assert listing_shots[0]["listing_id"] == "H001"
    assert "Professional copy variant A" in listing_shots[0]["narrative"]


def test_run_video_writes_artifacts(monkeypatch: Any, tmp_path: Path) -> None:
    run_dir = tmp_path / "20990109"
    run_dir.mkdir(parents=True, exist_ok=True)
    clean_rows = [
        {
            "listing_id": "H001",
            "district": "pudong",
            "community": "Demo Community",
            "layout": "2-1-1",
            "area_sqm": 89.3,
            "total_price_wan": 420.5,
            "title": "Demo listing title",
        }
    ]
    (run_dir / "clean_listings.json").write_text(json.dumps(clean_rows, ensure_ascii=False), encoding="utf-8")

    config = {
        "pipeline": {"video_top_n": 5},
        "content_generation": {"video_template": "default"},
    }

    def _fake_generate_template_video(storyboard: dict[str, Any], output_path: Path, **_: Any) -> dict[str, Any]:
        output_path.write_bytes(b"mock-video")
        return {
            "status": "mocked",
            "output_video": str(output_path),
            "duration_seconds": storyboard.get("total_duration_seconds", 0),
        }

    monkeypatch.setattr(pipeline, "generate_template_video", _fake_generate_template_video)

    report_path = pipeline.run_video(config, run_dir)

    assert report_path.exists()
    assert (run_dir / "video_storyboard.json").exists()
    assert (run_dir / "video_captions.srt").exists()
    assert (run_dir / "promo_video.mp4").exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "mocked"

