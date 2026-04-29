from __future__ import annotations

import argparse
from pathlib import Path

from property_workflow.orchestration.pipeline import execute_task


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw task runner bridge")
    parser.add_argument(
        "--task",
        required=True,
        choices=["collect", "clean", "analyze", "copywrite", "video", "publish", "full"],
        help="Pipeline task name",
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
        runner="openclaw-bridge",
    )


if __name__ == "__main__":
    raise SystemExit(main())
