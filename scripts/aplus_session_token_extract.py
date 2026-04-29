from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

NAMESPACE_HOST_PATTERN = re.compile(
    r"namespace-[A-Za-z0-9_-]+-https?://([A-Za-z0-9.-]+\.(?:ke\.com|lianjia\.com|deyoulife\.com|koofang\.com))/"
    r"\D{0,6}(\d{1,3})",
    re.IGNORECASE,
)
DT_BLOCK_PATTERN = re.compile(
    r"map-(\d+)-dtSessionId(.{0,220}?)(?:map-\d+-|namespace-|next-map-id|$)",
    re.IGNORECASE | re.DOTALL,
)
RISK_BLOCK_PATTERN = re.compile(
    r"map-(\d+)-risk_uuid(.{0,280}?)(?:map-\d+-|namespace-|next-map-id|$)",
    re.IGNORECASE | re.DOTALL,
)


def _sanitize_token(value: str) -> str:
    if not value:
        return ""
    text = "".join(ch for ch in value if 32 <= ord(ch) <= 126).strip()
    if not text:
        return ""
    if "map-" in text:
        text = text.split("map-", 1)[0]
    if "__storage_test__" in text:
        text = text.split("__storage_test__", 1)[0]
    text = text.strip()
    match = re.search(r"[A-Za-z0-9][A-Za-z0-9_\-*=.:/]{7,180}", text)
    if match:
        text = match.group(0)
    text = text.rstrip(".,;:'\"")
    return text if len(text) >= 8 else ""


def _pick_latest_logs(session_dir: Path, max_logs: int) -> list[Path]:
    rows: list[Path] = []
    for path in session_dir.glob("*.log"):
        if not path.is_file():
            continue
        if path.stat().st_size <= 0:
            continue
        rows.append(path)
    rows.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return rows[: max(max_logs, 1)]


def extract_session_host_tokens(session_dir: Path, max_logs: int = 2) -> dict[str, Any]:
    host_by_map: dict[str, str] = {}
    dt_by_map: dict[str, str] = {}
    risk_by_map: dict[str, str] = {}
    files = _pick_latest_logs(session_dir=session_dir, max_logs=max_logs)
    namespace_count = 0

    for path in files:
        try:
            text = path.read_bytes().decode("utf-8", errors="ignore")
        except OSError:
            continue
        namespace_count += len(re.findall(r"namespace-[A-Za-z0-9_\\-]+-https?://", text))

        for host, map_id in NAMESPACE_HOST_PATTERN.findall(text):
            if map_id not in host_by_map:
                host_by_map[map_id] = host.lower()
        for map_id, raw in DT_BLOCK_PATTERN.findall(text):
            token = _sanitize_token(raw)
            if token:
                dt_by_map[map_id] = token
        for map_id, raw in RISK_BLOCK_PATTERN.findall(text):
            token = _sanitize_token(raw)
            if token:
                risk_by_map[map_id] = token

    host_data: dict[str, dict[str, str]] = {}
    for map_id, host in host_by_map.items():
        dt_session_id = dt_by_map.get(map_id, "")
        risk_uuid = risk_by_map.get(map_id, "")
        if not dt_session_id and not risk_uuid:
            continue
        host_data[host] = {
            "map_id": map_id,
            "dtSessionId": dt_session_id,
            "risk_uuid": risk_uuid,
        }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "session_dir": str(session_dir),
        "files": [str(path) for path in files],
        "namespace_count": namespace_count,
        "host_data": host_data,
        "dt_by_map": dt_by_map,
        "risk_by_map": risk_by_map,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract A+ dtSessionId/risk_uuid by host from Session Storage logs")
    parser.add_argument(
        "--session-dir",
        default=str(Path.home() / "AppData/Roaming/A+/Session Storage"),
        help="A+ Session Storage directory",
    )
    parser.add_argument("--max-logs", type=int, default=2, help="Max recent *.log files to parse")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[1] / "runtime" / "session_host_tokens.json"),
        help="Output JSON path",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    session_dir = Path(args.session_dir).resolve()
    payload = extract_session_host_tokens(session_dir=session_dir, max_logs=args.max_logs)

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"[aplus-session-token-extract] hosts={len(payload.get('host_data', {}))} "
        f"dt={len(payload.get('dt_by_map', {}))} risk={len(payload.get('risk_by_map', {}))} -> {output_path}"
    )
    for host, token in list(payload.get("host_data", {}).items())[:20]:
        print(
            f"- host={host} map={token.get('map_id')} "
            f"dt={bool(token.get('dtSessionId'))} risk={bool(token.get('risk_uuid'))}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
