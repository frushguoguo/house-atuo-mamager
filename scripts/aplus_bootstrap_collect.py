from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from property_workflow.collectors.aplus_desktop import load_aplus_cookies
from property_workflow.config import load_config
from property_workflow.orchestration.pipeline import run_pipeline_task


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch A+ desktop and run collect task once cookies are ready")
    parser.add_argument(
        "--config",
        default="property-workflow-config.yaml",
        help="Path to workflow config",
    )
    parser.add_argument(
        "--task",
        default="collect",
        choices=["collect", "full"],
        help="Pipeline task to run after cookie check",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Runtime date token, e.g. 20260424",
    )
    parser.add_argument(
        "--aplus-exe",
        default=str(Path.home() / "AppData/Roaming/A+/A+.exe"),
        help="Path to A+ desktop executable",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Do not auto-launch A+ desktop",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=300,
        help="Max seconds to wait for valid cookies",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=3.0,
        help="Polling interval in seconds",
    )
    return parser


def _get_beike_desktop_options(config: dict[str, Any]) -> dict[str, Any]:
    for source in config.get("data_sources", []):
        if not isinstance(source, dict):
            continue
        if str(source.get("name", "")).strip().lower() != "beike":
            continue
        desktop = source.get("desktop_aplus")
        if isinstance(desktop, dict):
            return desktop
    raise ValueError("beike.desktop_aplus config not found")


def _resolve_aplus_path(
    config: dict[str, Any],
    desktop: dict[str, Any],
    key: str,
    default_name: str,
) -> Path:
    candidate = str(desktop.get(key, "")).strip()
    if candidate:
        return Path(candidate).resolve()
    base_paths = config.get("base_paths")
    if isinstance(base_paths, dict):
        aplus_root = str(base_paths.get("aplus_root", "")).strip()
        if aplus_root:
            return (Path(aplus_root) / default_name).resolve()
    return (Path.home() / "AppData/Roaming/A+" / default_name).resolve()


def _force_beike_desktop_collect(config: dict[str, Any]) -> None:
    for source in config.get("data_sources", []):
        if not isinstance(source, dict):
            continue
        if str(source.get("name", "")).strip().lower() != "beike":
            continue
        desktop = source.get("desktop_aplus")
        if not isinstance(desktop, dict):
            desktop = {}
            source["desktop_aplus"] = desktop
        desktop["enabled"] = True
        if "auto_probe_enabled" not in desktop:
            desktop["auto_probe_enabled"] = True
        if "fallback_to_synthetic" not in desktop:
            desktop["fallback_to_synthetic"] = True
        return
    raise ValueError("beike data source not found")


def _wait_for_cookies(
    cookie_db_path: Path,
    local_state_path: Path | None,
    cookie_domains: list[str],
    wait_timeout: int,
    poll_seconds: float,
) -> dict[str, str]:
    deadline = time.time() + wait_timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            cookies = load_aplus_cookies(
                cookie_db_path=cookie_db_path,
                local_state_path=local_state_path,
                cookie_domains=cookie_domains,
            )
            if cookies:
                return cookies
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(poll_seconds)
    if last_error:
        raise TimeoutError(f"Timed out waiting for A+ cookies: {last_error}") from last_error
    raise TimeoutError("Timed out waiting for A+ cookies")


def _launch_aplus(exe_path: Path) -> None:
    if not exe_path.exists():
        raise FileNotFoundError(f"A+ executable not found: {exe_path}")
    subprocess.Popen([str(exe_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    args = _build_parser().parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    desktop = _get_beike_desktop_options(config)

    cookie_db_path = _resolve_aplus_path(config, desktop, "cookie_db_path", "Cookies")
    local_state_path = _resolve_aplus_path(config, desktop, "local_state_path", "Local State")
    cookie_domains_raw = desktop.get("cookie_domains", [".ke.com", ".lianjia.com"])
    cookie_domains = cookie_domains_raw if isinstance(cookie_domains_raw, list) else [".ke.com", ".lianjia.com"]

    if not args.no_launch:
        _launch_aplus(Path(args.aplus_exe).resolve())
        print(f"[aplus-bootstrap] launched A+: {args.aplus_exe}")
    print("[aplus-bootstrap] waiting for valid A+ cookies, scan login QR in desktop app if needed...")
    cookies = _wait_for_cookies(
        cookie_db_path=cookie_db_path,
        local_state_path=local_state_path,
        cookie_domains=[str(item) for item in cookie_domains],
        wait_timeout=args.wait_timeout,
        poll_seconds=args.poll_seconds,
    )
    print(f"[aplus-bootstrap] cookies ready: {len(cookies)}")

    _force_beike_desktop_collect(config)
    temp_config = config_path.parent / ".aplus_bootstrap_config.json"
    temp_config.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[aplus-bootstrap] temporary config prepared: {temp_config}")

    try:
        run_dir = run_pipeline_task(
            task=args.task,
            config_path=temp_config,
            date_token=args.date,
        )
    finally:
        temp_config.unlink(missing_ok=True)
        print(f"[aplus-bootstrap] temporary config removed: {temp_config}")
    print(f"[aplus-bootstrap] task={args.task} finished, run_dir={run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
