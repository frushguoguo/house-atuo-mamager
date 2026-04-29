from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from property_workflow.collectors.aplus_desktop import apply_aplus_cookie_entries, load_aplus_cookie_entries
from property_workflow.collectors.aplus_endpoint_discovery import extract_path_method_hints_from_text


SCRIPT_SRC_PATTERN = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.IGNORECASE)
FULL_API_URL_PATTERN = re.compile(
    r"https?://([a-zA-Z0-9.-]+\.(?:ke\.com|lianjia\.com|koofang\.com))"
    r"(/(?:[A-Za-z0-9_-]+/)*api/[A-Za-z0-9_./-]+)",
    re.IGNORECASE,
)
API_PATH_PATTERN = re.compile(r"(/(?:[A-Za-z0-9_-]+/)*api/[A-Za-z0-9_./-]+)")
PROPERTY_KEYWORDS = ("deal", "house", "fang", "resblock", "listing", "estate", "focus", "history", "query")


def _normalize_api_path(value: str) -> str:
    text = value.strip()
    if not text.startswith("/") or "/api/" not in text:
        return ""
    if "?" in text:
        text = text.split("?", 1)[0]
    if "#" in text:
        text = text.split("#", 1)[0]
    if len(text) > 160:
        return ""
    if text.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".map", ".tgz")):
        return ""
    return text


def _is_property_api_path(path: str) -> bool:
    lowered = path.lower()
    return any(keyword in lowered for keyword in PROPERTY_KEYWORDS)


def _extract_script_urls(page_url: str, html: str) -> list[str]:
    rows: list[str] = []
    for match in SCRIPT_SRC_PATTERN.findall(html):
        script_url = urljoin(page_url, match)
        parsed = urlparse(script_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        rows.append(script_url)
    return sorted(set(rows))


def _extract_api_hints(text: str) -> tuple[set[str], set[str]]:
    paths: set[str] = set()
    urls: set[str] = set()
    for raw_path in API_PATH_PATTERN.findall(text):
        api_path = _normalize_api_path(raw_path)
        if api_path and _is_property_api_path(api_path):
            paths.add(api_path)
    for match in FULL_API_URL_PATTERN.finditer(text):
        host = match.group(1).lower()
        api_path = _normalize_api_path(match.group(2))
        if api_path and _is_property_api_path(api_path):
            urls.add(f"https://{host}{api_path}")
    return paths, urls


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan live A+ business pages and extract property api hints")
    parser.add_argument(
        "--targets",
        nargs="*",
        default=[
            "https://xinfang.a.ke.com",
            "https://house.link.lianjia.com",
            "https://deal.fang.lianjia.com",
            "https://linkconsole.fang.lianjia.com",
            "https://link.fang.lianjia.com",
        ],
        help="Business page targets to crawl",
    )
    parser.add_argument(
        "--cookie-db",
        default=str(Path.home() / "AppData/Roaming/A+/Cookies"),
        help="Path to A+ Chromium cookie DB",
    )
    parser.add_argument(
        "--local-state",
        default=str(Path.home() / "AppData/Roaming/A+/Local State"),
        help="Path to A+ Local State",
    )
    parser.add_argument(
        "--domains",
        nargs="*",
        default=[".ke.com", ".lianjia.com", "app.a.ke.com", "saas.a.ke.com"],
        help="Cookie domain filters",
    )
    parser.add_argument("--asset-limit", type=int, default=24, help="Max js assets fetched per target")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout seconds")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "runtime" / "aplus_live_api_scan.json"),
        help="Output JSON path",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    cookie_entries = load_aplus_cookie_entries(
        cookie_db_path=Path(args.cookie_db),
        local_state_path=Path(args.local_state),
        cookie_domains=args.domains,
    )
    if not cookie_entries:
        raise RuntimeError("No valid A+ cookies found")

    session = requests.Session()
    apply_aplus_cookie_entries(session=session, cookie_entries=cookie_entries)

    result: dict[str, object] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "targets": args.targets,
        "cookie_count": len(cookie_entries),
        "target_results": [],
        "property_api_paths": [],
        "full_api_urls": [],
        "path_method_hints": {},
    }
    all_paths: set[str] = set()
    all_urls: set[str] = set()
    all_method_hints: dict[str, set[str]] = {}

    for target in args.targets:
        target_paths: set[str] = set()
        target_urls: set[str] = set()
        item: dict[str, object] = {
            "target": target,
            "asset_urls": [],
            "property_api_paths": [],
            "full_api_urls": [],
            "path_method_hints": {},
        }
        try:
            response = session.get(target, timeout=args.timeout, allow_redirects=True)
            item["status_code"] = response.status_code
            item["final_url"] = response.url
            html = response.text
            paths, urls = _extract_api_hints(html)
            all_paths.update(paths)
            all_urls.update(urls)
            target_paths.update(paths)
            target_urls.update(urls)
            for api_path, methods in extract_path_method_hints_from_text(html).items():
                method_set = all_method_hints.setdefault(api_path, set())
                method_set.update(methods)

            scripts = _extract_script_urls(response.url, html)[: max(args.asset_limit, 0)]
            item["asset_urls"] = scripts
            for script_url in scripts:
                try:
                    asset_resp = session.get(script_url, timeout=args.timeout)
                    text = asset_resp.text
                    paths, urls = _extract_api_hints(text)
                    all_paths.update(paths)
                    all_urls.update(urls)
                    target_paths.update(paths)
                    target_urls.update(urls)
                    for api_path, methods in extract_path_method_hints_from_text(text).items():
                        method_set = all_method_hints.setdefault(api_path, set())
                        method_set.update(methods)
                except requests.RequestException:
                    continue
        except requests.RequestException as exc:
            item["error"] = str(exc)
        item["property_api_paths"] = sorted(target_paths)
        item["full_api_urls"] = sorted(target_urls)
        target_hints = {
            path: sorted(methods)
            for path, methods in all_method_hints.items()
            if path in target_paths and methods
        }
        item["path_method_hints"] = target_hints
        result["target_results"].append(item)

    result["property_api_paths"] = sorted(all_paths)
    result["full_api_urls"] = sorted(all_urls)
    result["path_method_hints"] = {
        path: sorted(methods)
        for path, methods in sorted(all_method_hints.items())
        if methods
    }

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"[aplus-live-api-scan] paths={len(result['property_api_paths'])} "
        f"full_urls={len(result['full_api_urls'])} -> {output_path}"
    )
    for path in result["property_api_paths"][:20]:
        print(f"- path={path}")
    for url in result["full_api_urls"][:20]:
        print(f"- url={url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
