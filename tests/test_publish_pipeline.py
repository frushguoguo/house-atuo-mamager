from __future__ import annotations

import json
from pathlib import Path

import property_workflow.orchestration.pipeline as pipeline
from property_workflow.publishing.engine import build_publish_bundle


def test_build_publish_bundle_prefers_copywriting() -> None:
    clean_rows = [
        {
            "listing_id": "H001",
            "source": "beike",
            "city": "shanghai",
            "district": "pudong",
            "community": "Demo Community",
            "title": "Fallback title",
            "layout": "2-1-1",
            "area_sqm": 89.0,
            "total_price_wan": 420.0,
            "url": "https://example.com/listing/H001",
        }
    ]
    copy_items = [{"listing_id": "H001", "variants": ["Primary copy"]}]

    bundle = build_publish_bundle(
        clean_rows,
        copy_items,
        top_n=3,
        call_to_action="Book a tour now.",
    )

    assert bundle["item_count"] == 1
    assert bundle["items"][0]["listing_id"] == "H001"
    assert "Primary copy" in bundle["items"][0]["caption"]
    assert "Book a tour now." in bundle["items"][0]["caption"]


def test_run_publish_generates_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "20990110"
    run_dir.mkdir(parents=True, exist_ok=True)

    clean_rows = [
        {
            "listing_id": "H001",
            "source": "beike",
            "city": "shanghai",
            "district": "pudong",
            "community": "Demo Community",
            "title": "Listing title",
            "layout": "2-1-1",
            "area_sqm": 89.0,
            "total_price_wan": 420.0,
            "url": "https://example.com/listing/H001",
        }
    ]
    copy_items = [{"listing_id": "H001", "variants": ["Publish copy"]}]

    (run_dir / "clean_listings.json").write_text(
        json.dumps(clean_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "copywriting.json").write_text(
        json.dumps(copy_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    config = {
        "pipeline": {"publish_top_n": 5},
        "content_generation": {"publish_call_to_action": "Book a tour now."},
        "publish_platforms": [
            {"name": "douyin", "enabled": True},
            {"name": "xiaohongshu", "enabled": True},
        ],
    }

    report_path = pipeline.run_publish(config, run_dir)

    assert report_path.exists()
    assert (run_dir / "publish_payload.json").exists()
    assert (run_dir / "publish_records_douyin.json").exists()
    assert (run_dir / "publish_records_xiaohongshu.json").exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "success"
    assert len(report["results"]) == 2
    assert report["success_platform_count"] == 2


def test_run_publish_with_sau_cli_dry_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "20990111"
    run_dir.mkdir(parents=True, exist_ok=True)

    clean_rows = [
        {
            "listing_id": "H001",
            "source": "beike",
            "city": "shanghai",
            "district": "pudong",
            "community": "Demo Community",
            "title": "Listing title",
            "layout": "2-1-1",
            "area_sqm": 89.0,
            "total_price_wan": 420.0,
            "url": "https://example.com/listing/H001",
        }
    ]
    copy_items = [{"listing_id": "H001", "variants": ["Publish copy"]}]
    video_path = run_dir / "promo_video.mp4"
    video_path.write_bytes(b"video")
    video_report = {
        "status": "success",
        "output_video": str(video_path),
        "duration_seconds": 10.0,
    }

    (run_dir / "clean_listings.json").write_text(
        json.dumps(clean_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "copywriting.json").write_text(
        json.dumps(copy_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "video_generation_report.json").write_text(
        json.dumps(video_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    sau_root = tmp_path / "social-auto-upload"
    sau_root.mkdir(parents=True, exist_ok=True)
    (sau_root / "sau_cli.py").write_text("print('ok')\n", encoding="utf-8")

    config = {
        "pipeline": {"publish_top_n": 5},
        "content_generation": {"publish_call_to_action": "Book a tour now."},
        "publish_platforms": [
            {
                "name": "douyin",
                "enabled": True,
                "publisher": "sau_cli",
                "sau_project_root": str(sau_root),
                "account": "agent001",
                "dry_run": True,
            }
        ],
    }

    report_path = pipeline.run_publish(config, run_dir)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "success"
    assert report["success_platform_count"] == 1
    assert report["results"][0]["mode"] == "sau_cli"
    assert report["results"][0]["dry_run"] is True
