from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from property_workflow.analysis.hotspot import build_hotspot_report, render_markdown_report
from property_workflow.cleaning.cleaner import clean_listings
from property_workflow.collectors.factory import create_collector
from property_workflow.config import load_config, resolve_base_path
from property_workflow.content.copywriter import generate_batch_copy
from property_workflow.content.video_generator import (
    build_video_storyboard,
    generate_template_video,
    render_storyboard_srt,
)
from property_workflow.publishing.engine import build_publish_bundle, publish_to_enabled_platforms


class PipelineError(RuntimeError):
    def __init__(
        self,
        *,
        error_code: str,
        exit_code: int,
        message: str,
        task: str | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.exit_code = exit_code
        self.message = message
        self.task = task
        self.path = path

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error_code": self.error_code,
            "exit_code": self.exit_code,
            "message": self.message,
        }
        if self.task:
            payload["task"] = self.task
        if self.path:
            payload["path"] = self.path
        return payload


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise PipelineError(
            error_code="E_INPUT_MISSING",
            exit_code=12,
            message=f"missing input file: {path}",
            path=str(path),
        )
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise PipelineError(
            error_code="E_INVALID_JSON",
            exit_code=13,
            message=f"invalid json file: {path}",
            path=str(path),
        ) from exc


def _today_token() -> str:
    return datetime.now().strftime("%Y%m%d")


def _run_dir(base_dir: Path, date_token: str | None = None) -> Path:
    token = date_token or _today_token()
    out = base_dir / token
    out.mkdir(parents=True, exist_ok=True)
    return out


def run_collect(config: dict[str, Any], run_dir: Path) -> Path:
    limit = int(config.get("pipeline", {}).get("sample_limit_per_source", 40))
    rows: list[dict[str, Any]] = []
    for source in config.get("data_sources", []):
        if not source.get("enabled", False):
            continue
        name = str(source.get("name", "")).strip()
        if not name:
            continue
        collector = create_collector(name)
        city = source.get("city", "unknown")
        districts = source.get("districts", []) or []
        rows.extend(collector.collect(city=city, districts=districts, limit=limit, options=source))

    output = run_dir / "raw_listings.json"
    _save_json(output, rows)
    print(f"[collect] done: {len(rows)} rows -> {output}")
    return output


def run_clean(run_dir: Path) -> Path:
    raw_rows = _load_json(run_dir / "raw_listings.json")
    cleaned = clean_listings(raw_rows)
    output = run_dir / "clean_listings.json"
    _save_json(output, cleaned)
    print(f"[clean] done: {len(cleaned)} rows -> {output}")
    return output


def run_analyze(run_dir: Path) -> Path:
    clean_rows = _load_json(run_dir / "clean_listings.json")
    report = build_hotspot_report(clean_rows)
    json_out = run_dir / "analysis_report.json"
    _save_json(json_out, report)

    md_out = run_dir / "analysis_report.md"
    md_out.write_text(render_markdown_report(report), encoding="utf-8")
    print(f"[analyze] done -> {json_out} | {md_out}")
    return json_out


def run_copywrite(config: dict[str, Any], run_dir: Path) -> Path:
    clean_rows = _load_json(run_dir / "clean_listings.json")
    style = str(config.get("content_generation", {}).get("copywriting_style", "professional"))
    top_n = int(config.get("pipeline", {}).get("copywriting_top_n", 10))
    payload = generate_batch_copy(clean_rows, style=style, top_n=top_n)
    output = run_dir / "copywriting.json"
    _save_json(output, payload)
    print(f"[copywrite] done: {len(payload)} items -> {output}")
    return output


def run_video(config: dict[str, Any], run_dir: Path) -> Path:
    clean_rows = _load_json(run_dir / "clean_listings.json")

    copywriting_items: list[dict[str, Any]] = []
    copy_path = run_dir / "copywriting.json"
    if copy_path.exists():
        try:
            copy_payload = _load_json(copy_path)
            if isinstance(copy_payload, list):
                copywriting_items = [item for item in copy_payload if isinstance(item, dict)]
        except Exception as exc:
            print(f"[video] skip invalid copywriting file: {copy_path} ({exc})")

    content_cfg = config.get("content_generation", {})
    template = str(content_cfg.get("video_template", "default"))
    bgm_path_raw = str(content_cfg.get("video_bgm_path", "")).strip()
    bgm_volume = float(content_cfg.get("video_bgm_volume", 0.18))
    bgm_path = Path(bgm_path_raw).expanduser().resolve() if bgm_path_raw else None
    top_n = int(config.get("pipeline", {}).get("video_top_n", 8))
    storyboard = build_video_storyboard(
        clean_rows,
        copywriting_items,
        template=template,
        max_items=top_n,
    )
    storyboard_out = run_dir / "video_storyboard.json"
    _save_json(storyboard_out, storyboard)

    srt_out = run_dir / "video_captions.srt"
    render_storyboard_srt(storyboard, srt_out)

    video_out = run_dir / "promo_video.mp4"
    report = generate_template_video(
        storyboard,
        video_out,
        captions_path=srt_out,
        template=template,
        bgm_path=bgm_path,
        bgm_volume=bgm_volume,
    )
    report["template"] = template
    report["storyboard_path"] = str(storyboard_out)
    report["captions_path"] = str(srt_out)

    report_out = run_dir / "video_generation_report.json"
    _save_json(report_out, report)
    print(f"[video] done: status={report.get('status')} -> {report_out}")
    return report_out


def run_publish(config: dict[str, Any], run_dir: Path) -> Path:
    clean_rows = _load_json(run_dir / "clean_listings.json")

    copywriting_items: list[dict[str, Any]] = []
    copy_path = run_dir / "copywriting.json"
    if copy_path.exists():
        try:
            copy_payload = _load_json(copy_path)
            if isinstance(copy_payload, list):
                copywriting_items = [item for item in copy_payload if isinstance(item, dict)]
        except Exception as exc:
            print(f"[publish] skip invalid copywriting file: {copy_path} ({exc})")

    video_report: dict[str, Any] | None = None
    video_report_path = run_dir / "video_generation_report.json"
    if video_report_path.exists():
        try:
            payload = _load_json(video_report_path)
            if isinstance(payload, dict):
                video_report = payload
        except Exception as exc:
            print(f"[publish] skip invalid video report: {video_report_path} ({exc})")

    pipeline_cfg = config.get("pipeline", {})
    top_n = int(pipeline_cfg.get("publish_top_n", pipeline_cfg.get("copywriting_top_n", 10)))
    call_to_action = str(
        config.get("content_generation", {}).get(
            "publish_call_to_action",
            "DM for details and viewing schedule.",
        )
    )
    bundle = build_publish_bundle(
        clean_rows,
        copywriting_items,
        video_report=video_report,
        run_dir=run_dir,
        top_n=top_n,
        call_to_action=call_to_action,
    )
    payload_out = run_dir / "publish_payload.json"
    _save_json(payload_out, bundle)

    report = publish_to_enabled_platforms(config, bundle, run_dir=run_dir)
    report["payload_path"] = str(payload_out)
    report["video_report_path"] = str(video_report_path) if video_report is not None else None

    report_out = run_dir / "publish_report.json"
    _save_json(report_out, report)
    print(f"[publish] done: status={report.get('status')} -> {report_out}")
    return report_out


def run_pipeline_task(task: str, config_path: Path, date_token: str | None = None) -> Path:
    try:
        config = load_config(config_path)
    except FileNotFoundError as exc:
        raise PipelineError(
            error_code="E_CONFIG_NOT_FOUND",
            exit_code=10,
            message=f"config file not found: {config_path}",
            task=task,
            path=str(config_path),
        ) from exc
    except Exception as exc:
        raise PipelineError(
            error_code="E_CONFIG_INVALID",
            exit_code=11,
            message=f"failed to load config: {config_path} ({exc})",
            task=task,
            path=str(config_path),
        ) from exc
    base_dir = resolve_base_path(config, "runtime_root", "runtime", anchor=config_path.parent.resolve())
    run_dir = _run_dir(base_dir, date_token=date_token)

    if task == "collect":
        run_collect(config, run_dir)
    elif task == "clean":
        run_clean(run_dir)
    elif task == "analyze":
        run_analyze(run_dir)
    elif task == "copywrite":
        run_copywrite(config, run_dir)
    elif task == "video":
        run_video(config, run_dir)
    elif task == "publish":
        run_publish(config, run_dir)
    elif task == "full":
        run_collect(config, run_dir)
        run_clean(run_dir)
        run_analyze(run_dir)
        run_copywrite(config, run_dir)
    else:
        raise PipelineError(
            error_code="E_TASK_UNKNOWN",
            exit_code=14,
            message=f"unknown task: {task}",
            task=task,
        )
    return run_dir


def execute_task(task: str, config_path: Path, date_token: str | None = None, *, runner: str = "pipeline") -> int:
    try:
        run_dir = run_pipeline_task(task=task, config_path=config_path, date_token=date_token)
        print(f"[{runner}] task={task} finished, run_dir={run_dir}")
        return 0
    except PipelineError as exc:
        payload = exc.to_dict()
        payload["task"] = task
        print(f"[{runner}][error] {json.dumps(payload, ensure_ascii=False)}")
        return exc.exit_code
    except Exception as exc:
        payload = {
            "ok": False,
            "error_code": "E_INTERNAL",
            "exit_code": 99,
            "task": task,
            "message": str(exc),
        }
        print(f"[{runner}][error] {json.dumps(payload, ensure_ascii=False)}")
        return 99


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Property workflow pipeline")
    parser.add_argument(
        "--task",
        required=True,
        choices=["collect", "clean", "analyze", "copywrite", "video", "publish", "full"],
        help="Task name to run",
    )
    parser.add_argument(
        "--config",
        default="property-workflow-config.yaml",
        help="Config file path",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Run date token (for example: 20260424)",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    return execute_task(
        task=args.task,
        config_path=Path(args.config).resolve(),
        date_token=args.date,
        runner="pipeline",
    )


if __name__ == "__main__":
    raise SystemExit(main())
