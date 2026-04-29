from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from property_workflow.collectors.aplus_desktop import apply_aplus_cookie_entries, load_aplus_cookie_entries
from property_workflow.collectors.aplus_endpoint_discovery import discover_aplus_endpoints, save_discovery_payload
from property_workflow.config import load_config, resolve_base_path
from property_workflow.orchestration.pipeline import run_pipeline_task


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A+ unattended daemon: refresh auth, discover endpoints, run collect")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "property-workflow-config.yaml"), help="Config path")
    parser.add_argument("--aplus-exe", default=str(Path.home() / "AppData/Roaming/A+/A+.exe"), help="A+ exe path")
    parser.add_argument("--no-auto-launch", action="store_true", help="Do not auto launch A+ when process is absent")
    parser.add_argument("--auth-interval", type=int, default=300, help="Auth refresh interval (seconds)")
    parser.add_argument("--discovery-interval", type=int, default=1800, help="Endpoint discovery interval (seconds)")
    parser.add_argument(
        "--collect-task",
        choices=["none", "collect", "full"],
        default="none",
        help="Optional pipeline task interval execution",
    )
    parser.add_argument("--collect-interval", type=int, default=1800, help="Collect interval (seconds)")
    parser.add_argument(
        "--auth-snapshot",
        default="aplus_auth_state.json",
        help="Where to write auth state snapshot",
    )
    parser.add_argument("--keepalive-url", default="https://saas.a.ke.com/cas", help="Keepalive URL")
    parser.add_argument("--skip-live-scan", action="store_true", help="Skip live api scan before discovery")
    parser.add_argument("--live-scan-timeout", type=int, default=180, help="Live api scan timeout (seconds)")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    return parser


def _is_aplus_running() -> bool:
    cmd = "(@(Get-Process -Name 'A+' -ErrorAction SilentlyContinue).Count)"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    count_text = (result.stdout or "").strip()
    try:
        return int(count_text) > 0
    except ValueError:
        return False


def _launch_aplus(exe_path: Path) -> None:
    if not exe_path.exists():
        raise FileNotFoundError(f"A+ executable not found: {exe_path}")
    subprocess.Popen([str(exe_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


def _resolve_runtime_root(config: dict[str, Any], config_path: Path) -> Path:
    return resolve_base_path(config, "runtime_root", "runtime", anchor=config_path.parent)


def _resolve_runtime_output_path(runtime_root: Path, path_text: str) -> Path:
    target = Path(path_text)
    if target.is_absolute():
        return target.resolve()
    relative_text = str(target).replace("\\", "/")
    if relative_text.startswith("runtime/"):
        relative_text = relative_text[len("runtime/") :]
    if relative_text == "runtime":
        relative_text = ""
    return (runtime_root / relative_text).resolve()


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
        desktop.setdefault("auto_probe_enabled", True)
        desktop.setdefault("fallback_to_synthetic", True)
        return
    raise ValueError("beike data source not found")


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _pick_code_cache_files(code_cache_js_dir: Path, max_files: int = 120) -> list[Path]:
    if not code_cache_js_dir.exists() or max_files <= 0:
        return []
    rows: list[Path] = []
    for path in code_cache_js_dir.glob("*"):
        if not path.is_file():
            continue
        if path.stat().st_size < 512:
            continue
        rows.append(path)
    rows.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return rows[:max_files]


def _refresh_auth_snapshot(
    config: dict[str, Any],
    runtime_root: Path,
    desktop: dict[str, Any],
    snapshot_path: Path,
    keepalive_url: str,
) -> dict[str, Any]:
    cookie_db_path = _resolve_aplus_path(config, desktop, "cookie_db_path", "Cookies")
    local_state_path = _resolve_aplus_path(config, desktop, "local_state_path", "Local State")
    domains = desktop.get("cookie_domains", [".ke.com", ".lianjia.com"])
    cookie_domains = [str(item) for item in domains] if isinstance(domains, list) else [".ke.com", ".lianjia.com"]

    payload: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cookie_db_path": str(cookie_db_path),
        "local_state_path": str(local_state_path) if local_state_path else "",
        "cookie_domains": cookie_domains,
        "keepalive_url": keepalive_url,
    }

    token_extract_script = PROJECT_ROOT / "scripts" / "aplus_session_token_extract.py"
    if token_extract_script.exists():
        try:
            token_output = (runtime_root / "session_host_tokens.json").resolve()
            subprocess.run(
                [sys.executable, str(token_extract_script), "--output", str(token_output)],
                check=False,
                timeout=45,
            )
            payload["session_token_path"] = str(token_output)
        except Exception:
            pass

    try:
        cookie_entries = load_aplus_cookie_entries(
            cookie_db_path=cookie_db_path,
            local_state_path=local_state_path,
            cookie_domains=cookie_domains,
        )
        cookies = {
            str(item.get("name", "")).strip(): str(item.get("value", "")).strip()
            for item in cookie_entries
            if str(item.get("name", "")).strip() and str(item.get("value", "")).strip()
        }
        payload["cookie_count"] = len(cookies)
        payload["cookie_entry_count"] = len(cookie_entries)
        payload["cookie_names"] = sorted(cookies.keys())
        payload["status"] = "ok" if cookies else "empty"
        if cookies and keepalive_url:
            session = requests.Session()
            apply_aplus_cookie_entries(session=session, cookie_entries=cookie_entries)
            try:
                response = session.get(keepalive_url, timeout=15, allow_redirects=False)
                payload["keepalive_status_code"] = response.status_code
                payload["keepalive_location"] = response.headers.get("Location", "")
            except requests.RequestException as exc:
                payload["keepalive_error"] = str(exc)

            seed_hosts_raw = desktop.get(
                "sso_seed_hosts",
                [
                    "xinfang.a.ke.com",
                    "deal.fang.lianjia.com",
                    "linkconsole.fang.lianjia.com",
                ],
            )
            seed_hosts = [str(item).strip().lower() for item in seed_hosts_raw if str(item).strip()]
            seed_results: list[dict[str, Any]] = []
            for host in seed_hosts:
                service_url = f"https://{host}/login"
                cas_url = f"https://login.ke.com/login?service={quote(service_url, safe=':/?=&')}"
                item: dict[str, Any] = {"host": host, "cas_url": cas_url}
                try:
                    cas_resp = session.get(cas_url, timeout=12, allow_redirects=True)
                    item["cas_status"] = cas_resp.status_code
                    item["cas_final_url"] = cas_resp.url
                except requests.RequestException as exc:
                    item["cas_error"] = str(exc)
                    seed_results.append(item)
                    continue
                try:
                    host_resp = session.get(f"https://{host}/", timeout=12, allow_redirects=False)
                    item["home_status"] = host_resp.status_code
                    item["home_location"] = host_resp.headers.get("Location", "")
                except requests.RequestException as exc:
                    item["home_error"] = str(exc)
                seed_results.append(item)
            payload["sso_seed_results"] = seed_results
    except Exception as exc:  # noqa: BLE001
        payload["status"] = "error"
        payload["error"] = str(exc)

    _save_json(snapshot_path, payload)
    return payload


def _discover_endpoints(
    runtime_root: Path,
    desktop: dict[str, Any],
    output_path: Path,
    run_live_scan: bool,
    live_scan_timeout_seconds: int,
) -> dict[str, Any]:
    resources_js_dir = Path(str(Path.home() / "AppData/Roaming/A+/resources/app/js")).resolve()
    code_cache_js_dir = Path(str(Path.home() / "AppData/Roaming/A+/Code Cache/js")).resolve()
    local_dump_default = (runtime_root / "local_storage_log_dump.txt").resolve()
    local_dump = local_dump_default if local_dump_default.exists() else None
    live_scan_output = (runtime_root / "aplus_live_api_scan.json").resolve()
    click_capture_output = (runtime_root / "aplus_click_capture.json").resolve()

    if run_live_scan:
        live_scan_script = PROJECT_ROOT / "scripts" / "aplus_live_api_scan.py"
        if live_scan_script.exists():
            try:
                subprocess.run(
                    [sys.executable, str(live_scan_script), "--output", str(live_scan_output)],
                    check=False,
                    timeout=max(live_scan_timeout_seconds, 10),
                )
            except Exception:
                pass

    extra_files: list[Path] = []
    if live_scan_output.exists():
        extra_files.append(live_scan_output)
    if click_capture_output.exists():
        extra_files.append(click_capture_output)
    extra_files.extend(_pick_code_cache_files(code_cache_js_dir, max_files=120))

    payload = discover_aplus_endpoints(
        resources_js_dir=resources_js_dir if resources_js_dir.exists() else None,
        local_storage_dump=local_dump,
        extra_scan_files=extra_files,
    )
    payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
    payload["resources_js_dir"] = str(resources_js_dir)
    payload["local_storage_dump"] = str(local_dump) if local_dump else ""
    payload["code_cache_js_dir"] = str(code_cache_js_dir)

    existing_candidates = desktop.get("auto_probe_candidates")
    if isinstance(existing_candidates, list) and existing_candidates:
        payload["endpoint_candidates"] = existing_candidates + payload.get("endpoint_candidates", [])

    save_discovery_payload(output_path, payload)
    return payload


def _run_collect_task(config_path: Path, task: str) -> Path:
    config = load_config(config_path)
    _force_beike_desktop_collect(config)
    temp_config = config_path.parent / ".aplus_unattended_config.json"
    temp_config.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        return run_pipeline_task(task=task, config_path=temp_config, date_token=None)
    finally:
        temp_config.unlink(missing_ok=True)


def main() -> int:
    args = _build_parser().parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    desktop = _get_beike_desktop_options(config)
    runtime_root = _resolve_runtime_root(config, config_path)
    snapshot_path = _resolve_runtime_output_path(runtime_root, args.auth_snapshot)
    discovery_path = (runtime_root / "aplus_endpoint_discovery.json").resolve()

    if not args.no_auto_launch and not _is_aplus_running():
        _launch_aplus(Path(args.aplus_exe).resolve())
        print(f"[aplus-daemon] launched A+: {args.aplus_exe}")

    next_auth = 0.0
    next_discovery = 0.0
    next_collect = 0.0

    while True:
        now = time.time()

        if now >= next_auth:
            if not args.no_auto_launch and not _is_aplus_running():
                _launch_aplus(Path(args.aplus_exe).resolve())
                print("[aplus-daemon] A+ restarted")
            auth_payload = _refresh_auth_snapshot(
                config=config,
                runtime_root=runtime_root,
                desktop=desktop,
                snapshot_path=snapshot_path,
                keepalive_url=args.keepalive_url,
            )
            print(
                f"[aplus-daemon] auth refreshed: status={auth_payload.get('status')} "
                f"cookies={auth_payload.get('cookie_count', 0)} -> {snapshot_path}"
            )
            next_auth = now + max(args.auth_interval, 10)

        if now >= next_discovery:
            discovery = _discover_endpoints(
                runtime_root=runtime_root,
                desktop=desktop,
                output_path=discovery_path,
                run_live_scan=not args.skip_live_scan,
                live_scan_timeout_seconds=args.live_scan_timeout,
            )
            print(
                f"[aplus-daemon] endpoint discovery refreshed: hosts={len(discovery.get('hosts', []))} "
                f"candidates={len(discovery.get('endpoint_candidates', []))} -> {discovery_path}"
            )
            next_discovery = now + max(args.discovery_interval, 30)

        if args.collect_task != "none" and now >= next_collect:
            run_dir = _run_collect_task(config_path=config_path, task=args.collect_task)
            print(f"[aplus-daemon] collect task={args.collect_task} finished: {run_dir}")
            next_collect = now + max(args.collect_interval, 60)

        if args.once:
            break
        time.sleep(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
