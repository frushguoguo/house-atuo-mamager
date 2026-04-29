from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse


HOST_PATTERN = re.compile(r"https?://([a-zA-Z0-9.-]+\.(?:ke\.com|lianjia\.com|koofang\.com))", re.IGNORECASE)
FULL_API_URL_PATTERN = re.compile(
    r"https?://([a-zA-Z0-9.-]+\.(?:ke\.com|lianjia\.com|koofang\.com))"
    r"(/(?:[A-Za-z0-9_-]+/)*api/[A-Za-z0-9_./-]+)",
    re.IGNORECASE,
)
API_PATH_PATTERN = re.compile(r"(/(?:[A-Za-z0-9_-]+/)*api/[A-Za-z0-9_./-]+)")
METHOD_URL_PATTERN = re.compile(
    r"(?P<method>get|post|put|patch|delete)\s*\(\s*\{[^{}]{0,600}?"
    r"url\s*:\s*[\"'](?P<path>/(?:[A-Za-z0-9_-]+/)*api/[A-Za-z0-9_./-]+)[\"']",
    re.IGNORECASE,
)
URL_METHOD_PATTERN = re.compile(
    r"url\s*:\s*[\"'](?P<path>/(?:[A-Za-z0-9_-]+/)*api/[A-Za-z0-9_./-]+)[\"'][^{}]{0,260}?"
    r"method\s*:\s*[\"'](?P<method>get|post|put|patch|delete)[\"']",
    re.IGNORECASE,
)
API_PROP_PATTERN = re.compile(
    r"api\s*:\s*[\"'](?P<path>/(?:[A-Za-z0-9_-]+/)*api/[A-Za-z0-9_./-]+)[\"']",
    re.IGNORECASE,
)
FETCH_PATH_PATTERN = re.compile(
    r"fetch\s*\(\s*[\"'](?P<path>/(?:[A-Za-z0-9_-]+/)*api/[A-Za-z0-9_./-]+)[\"']",
    re.IGNORECASE,
)


COMMON_LIST_PATHS = [
    "/api/deal/list",
    "/api/deal/historyList",
    "/api/house/list",
    "/api/house/historyList",
    "/api/wolverine/houseFocus/queryHouseList",
    "/api/houseFocus/queryHouseList",
]
PROPERTY_KEYWORDS = ("deal", "house", "fang", "resblock", "listing", "estate", "focus", "history", "query")
DOMAIN_SUFFIXES = (".ke.com", ".lianjia.com", ".koofang.com")
PAGE_PARAM_KEYS = ("pageNo", "currentPage", "page", "pageNum")
PAGE_SIZE_PARAM_KEYS = ("pageSize", "limit", "page_size", "pageLimit")


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _score_host(host: str) -> int:
    score = 0
    lowered = host.lower()
    if "house" in lowered:
        score += 4
    if "fang" in lowered:
        score += 4
    if "xinfang" in lowered:
        score += 4
    if "link" in lowered:
        score += 2
    if lowered.endswith(".lianjia.com"):
        score += 2
    if lowered.endswith(".a.ke.com"):
        score += 2
    if lowered in {"house.link.lianjia.com", "deal.fang.lianjia.com", "xinfang.a.ke.com"}:
        score += 6
    return score


def extract_hosts_from_text(text: str) -> list[str]:
    hosts = {match.group(1).lower() for match in HOST_PATTERN.finditer(text)}
    return sorted(hosts)


def _normalize_api_path(path: str) -> str:
    value = path.strip()
    if not value.startswith("/") or "/api/" not in value:
        return ""
    if "?" in value:
        value = value.split("?", 1)[0]
    if "#" in value:
        value = value.split("#", 1)[0]
    if len(value) > 160:
        return ""
    if value.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".tgz", ".map")):
        return ""
    return value


def _is_property_api_path(path: str) -> bool:
    lowered = path.lower()
    return any(keyword in lowered for keyword in PROPERTY_KEYWORDS)


def _is_supported_host(host: str) -> bool:
    lowered = host.lower().strip()
    return bool(lowered and lowered.endswith(DOMAIN_SUFFIXES))


def _is_property_business_path(path: str) -> bool:
    lowered = str(path or "").lower()
    if not lowered or lowered == "/":
        return False
    if lowered.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".map")):
        return False
    if any(keyword in lowered for keyword in PROPERTY_KEYWORDS):
        return True
    if any(token in lowered for token in ("/search/", "/pc/risk/", "/layer/")):
        return True
    return False


def _normalize_endpoint_url(raw_url: str) -> tuple[str, str, str, list[tuple[str, str]]] | None:
    text = str(raw_url or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    host = parsed.netloc.lower().strip()
    if not host or not _is_supported_host(host):
        return None
    path = parsed.path or "/"
    if len(path) > 220:
        return None
    endpoint = f"https://{host}{path}"
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    return endpoint, host, path, query_pairs


def _pick_param_name(keys: list[str], candidates: tuple[str, ...], default: str) -> str:
    key_set = {key.lower(): key for key in keys}
    for name in candidates:
        lowered = name.lower()
        if lowered in key_set:
            return key_set[lowered]
    return default


def _score_cdp_candidate_path(path: str) -> int:
    lowered = path.lower()
    score = 0
    if "/search/" in lowered:
        score += 24
    if "/api/" in lowered:
        score += 20
    if "query" in lowered:
        score += 12
    if "list" in lowered:
        score += 10
    if "/pc/risk/" in lowered:
        score += 7
    if "/layer/" in lowered:
        score += 4
    if "welcome/ping" in lowered:
        score -= 40
    return score


def _add_hint(hints: dict[str, set[str]], path: str, method: str) -> None:
    api_path = _normalize_api_path(path)
    if not api_path or not _is_property_api_path(api_path):
        return
    method_text = str(method).strip().upper()
    if method_text not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return
    hints.setdefault(api_path, set()).add(method_text)


def _extract_path_method_hints_sets(text: str) -> dict[str, set[str]]:
    hints: dict[str, set[str]] = {}

    for match in METHOD_URL_PATTERN.finditer(text):
        _add_hint(hints, match.group("path"), match.group("method"))
    for match in URL_METHOD_PATTERN.finditer(text):
        _add_hint(hints, match.group("path"), match.group("method"))
    for match in FETCH_PATH_PATTERN.finditer(text):
        _add_hint(hints, match.group("path"), "GET")
    for match in API_PROP_PATTERN.finditer(text):
        _add_hint(hints, match.group("path"), "GET")
        _add_hint(hints, match.group("path"), "POST")

    return hints


def extract_path_method_hints_from_text(text: str) -> dict[str, list[str]]:
    hints = _extract_path_method_hints_sets(text)
    return {path: sorted(methods) for path, methods in sorted(hints.items())}


def discover_hosts_from_files(
    paths: list[Path],
) -> tuple[list[dict[str, Any]], list[str], list[str], dict[str, list[str]]]:
    hits: dict[str, dict[str, Any]] = {}
    discovered_property_paths: set[str] = set()
    discovered_full_api_urls: set[str] = set()
    path_method_hints: dict[str, set[str]] = {}
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = _safe_read_text(path)
        if not text:
            continue

        for host in extract_hosts_from_text(text):
            item = hits.setdefault(
                host,
                {
                    "host": host,
                    "score": _score_host(host),
                    "sources": [],
                },
            )
            item["sources"].append(str(path))

        for match in FULL_API_URL_PATTERN.finditer(text):
            host = match.group(1).lower()
            api_path = _normalize_api_path(match.group(2))
            if not api_path:
                continue
            if _is_property_api_path(api_path):
                discovered_full_api_urls.add(f"https://{host}{api_path}")

        for raw_path in API_PATH_PATTERN.findall(text):
            api_path = _normalize_api_path(raw_path)
            if not api_path:
                continue
            if _is_property_api_path(api_path):
                discovered_property_paths.add(api_path)

        for api_path, methods in _extract_path_method_hints_sets(text).items():
            path_method_hints.setdefault(api_path, set()).update(methods)

    ranked = sorted(hits.values(), key=lambda x: (x["score"], x["host"]), reverse=True)
    normalized_hints = {path: sorted(methods) for path, methods in sorted(path_method_hints.items())}
    return ranked, sorted(discovered_property_paths), sorted(discovered_full_api_urls), normalized_hints


def _method_sequence(path: str, path_method_hints: dict[str, set[str]] | None = None) -> list[str]:
    hinted = (path_method_hints or {}).get(path, set())
    if hinted:
        methods = []
        for method in ("POST", "GET", "PUT", "PATCH", "DELETE"):
            if method in hinted:
                methods.append(method)
        if methods:
            return methods
    return ["POST", "GET"]


def _score_property_path(path: str) -> int:
    lowered = path.lower()
    score = 0
    if lowered.startswith("/new/api/"):
        score += 10
    if "/list" in lowered:
        score += 8
    if "query" in lowered:
        score += 5
    if "/deal/" in lowered:
        score += 5
    if "/house/" in lowered:
        score += 4
    if "resblock" in lowered:
        score += 3
    if "cashcow" in lowered:
        score -= 6
    if "/cfg/" in lowered:
        score -= 5
    if "/source/" in lowered:
        score -= 2
    return score


def _build_host_candidates(
    host: str,
    extra_property_paths: list[str] | None = None,
    path_method_hints: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    paths: list[str] = []
    if extra_property_paths:
        prioritized_extra = sorted(
            extra_property_paths,
            key=lambda value: (_score_property_path(value), value),
            reverse=True,
        )
        for value in prioritized_extra:
            if value not in paths:
                paths.append(value)
    for value in COMMON_LIST_PATHS:
        if value not in paths:
            paths.append(value)
    for path in paths:
        for method in _method_sequence(path, path_method_hints=path_method_hints):
            rows.append(
                {
                    "endpoint": f"https://{host}{path}",
                    "method": method,
                    "page_param": "pageNo",
                    "page_size_param": "pageSize",
                    "page_in": "body" if method in {"POST", "PUT", "PATCH"} else "params",
                }
            )
    return rows


def _candidate_from_url(endpoint: str, method: str) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "method": method,
        "page_param": "pageNo",
        "page_size_param": "pageSize",
        "page_in": "body" if method == "POST" else "params",
    }


def build_endpoint_candidates(
    host_rows: list[dict[str, Any]],
    max_hosts: int = 8,
    extra_property_paths: list[str] | None = None,
    full_api_urls: list[str] | None = None,
    path_method_hints: dict[str, set[str]] | None = None,
    direct_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    if direct_candidates:
        for raw in direct_candidates:
            if not isinstance(raw, dict):
                continue
            endpoint = str(raw.get("endpoint", "")).strip()
            method = str(raw.get("method", "GET")).strip().upper()
            if not endpoint or method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            key = (method, endpoint)
            if key in seen:
                continue
            seen.add(key)
            candidate = {
                "endpoint": endpoint,
                "method": method,
                "page_param": str(raw.get("page_param", "pageNo") or "pageNo"),
                "page_size_param": str(raw.get("page_size_param", "pageSize") or "pageSize"),
                "page_in": str(
                    raw.get(
                        "page_in",
                        "body" if method in {"POST", "PUT", "PATCH"} else "params",
                    )
                ),
            }
            if "page_size_in" in raw:
                candidate["page_size_in"] = str(raw.get("page_size_in") or candidate["page_in"])
            if isinstance(raw.get("base_params"), dict):
                candidate["base_params"] = dict(raw["base_params"])
            if isinstance(raw.get("json_body"), dict):
                candidate["json_body"] = dict(raw["json_body"])
            if isinstance(raw.get("headers"), dict):
                candidate["headers"] = dict(raw["headers"])
            if raw.get("response_path"):
                candidate["response_path"] = raw["response_path"]
            endpoints.append(candidate)

    if full_api_urls:
        for endpoint in full_api_urls:
            path = _normalize_api_path(re.sub(r"^https?://[^/]+", "", endpoint))
            for method in _method_sequence(path, path_method_hints=path_method_hints):
                key = (method, endpoint)
                if key in seen:
                    continue
                seen.add(key)
                endpoints.append(_candidate_from_url(endpoint, method))
    for row in host_rows[:max_hosts]:
        host = str(row.get("host", "")).strip().lower()
        if not host:
            continue
        for candidate in _build_host_candidates(
            host,
            extra_property_paths=extra_property_paths,
            path_method_hints=path_method_hints,
        ):
            key = (candidate["method"], candidate["endpoint"])
            if key in seen:
                continue
            seen.add(key)
            endpoints.append(candidate)
    return endpoints


def discover_aplus_endpoints(
    resources_js_dir: Path | None,
    local_storage_dump: Path | None,
    extra_scan_files: list[Path] | None = None,
) -> dict[str, Any]:
    scan_files: list[Path] = []

    if resources_js_dir and resources_js_dir.exists():
        scan_files.extend(sorted(resources_js_dir.rglob("*.js")))
    if local_storage_dump and local_storage_dump.exists():
        scan_files.append(local_storage_dump)
    if extra_scan_files:
        scan_files.extend(extra_scan_files)

    host_rows, property_paths, full_api_urls, path_method_hints = discover_hosts_from_files(scan_files)

    host_score_adjust: dict[str, int] = {}
    direct_candidates: list[dict[str, Any]] = []

    if extra_scan_files:
        for path in extra_scan_files:
            if path.suffix.lower() != ".json" or not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            raw_paths = payload.get("property_api_paths", [])
            if isinstance(raw_paths, list):
                for value in raw_paths:
                    api_path = _normalize_api_path(str(value))
                    if api_path and _is_property_api_path(api_path) and api_path not in property_paths:
                        property_paths.append(api_path)

            raw_urls = payload.get("full_api_urls", [])
            if isinstance(raw_urls, list):
                for value in raw_urls:
                    text = str(value).strip()
                    if not text:
                        continue
                    if text not in full_api_urls:
                        full_api_urls.append(text)

            raw_hints = payload.get("path_method_hints", {})
            if isinstance(raw_hints, dict):
                for raw_path, raw_methods in raw_hints.items():
                    api_path = _normalize_api_path(str(raw_path))
                    if not api_path or not _is_property_api_path(api_path):
                        continue
                    hints = path_method_hints.setdefault(api_path, [])
                    if isinstance(raw_methods, list):
                        for method in raw_methods:
                            method_text = str(method).strip().upper()
                            if method_text in {"GET", "POST", "PUT", "PATCH", "DELETE"} and method_text not in hints:
                                hints.append(method_text)
                    hints.sort()

            # Parse CDP capture json generated by scripts/aplus_cdp_capture.js
            response_path_by_endpoint_method: dict[tuple[str, str], str] = {}
            responses = payload.get("responses", [])
            if isinstance(responses, list):
                for row in responses:
                    if not isinstance(row, dict):
                        continue
                    dict_rows = int(row.get("dictRowCount", 0) or 0)
                    if dict_rows <= 0:
                        continue
                    list_path = str(row.get("listPath", "")).strip()
                    if not list_path:
                        continue
                    method = str(row.get("method", "GET")).strip().upper()
                    normalized = _normalize_endpoint_url(str(row.get("url", "")))
                    if normalized is None:
                        continue
                    endpoint, host, cdp_path, _ = normalized
                    if not _is_property_business_path(cdp_path):
                        continue
                    response_path_by_endpoint_method[(method, endpoint)] = list_path
                    host_score_adjust[host] = host_score_adjust.get(host, 0) + 10

            requests_rows = payload.get("requests", [])
            if isinstance(requests_rows, list):
                seen_cdp_candidates: set[tuple[str, str]] = set()
                for row in requests_rows:
                    if not isinstance(row, dict):
                        continue
                    method = str(row.get("method", "GET")).strip().upper()
                    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                        continue
                    normalized = _normalize_endpoint_url(str(row.get("url", "")))
                    if normalized is None:
                        continue
                    endpoint, host, cdp_path, query_pairs = normalized
                    if not _is_property_business_path(cdp_path):
                        continue
                    key = (method, endpoint)
                    if key in seen_cdp_candidates:
                        continue
                    seen_cdp_candidates.add(key)

                    query_keys = [k for k, _ in query_pairs if k]
                    page_param = _pick_param_name(query_keys, PAGE_PARAM_KEYS, "pageNo")
                    page_size_param = _pick_param_name(query_keys, PAGE_SIZE_PARAM_KEYS, "")
                    base_params: dict[str, Any] = {}
                    for raw_key, raw_value in query_pairs:
                        key_text = str(raw_key).strip()
                        if not key_text:
                            continue
                        if key_text == page_param:
                            continue
                        if page_size_param and key_text == page_size_param:
                            continue
                        if key_text not in base_params:
                            base_params[key_text] = raw_value

                    candidate: dict[str, Any] = {
                        "endpoint": endpoint,
                        "method": method,
                        "page_param": page_param,
                        "page_size_param": page_size_param,
                        "page_in": "body" if method in {"POST", "PUT", "PATCH"} else "params",
                    }
                    if base_params:
                        candidate["base_params"] = base_params
                    list_path = response_path_by_endpoint_method.get((method, endpoint))
                    if list_path:
                        candidate["response_path"] = list_path

                    direct_candidates.append(candidate)
                    host_score_adjust[host] = host_score_adjust.get(host, 0) + _score_cdp_candidate_path(cdp_path)

            target_results = payload.get("target_results", [])
            if isinstance(target_results, list):
                for row in target_results:
                    if not isinstance(row, dict):
                        continue
                    target = str(row.get("target", "")).strip()
                    host = urlparse(target).netloc.lower()
                    if not host:
                        continue
                    adjust = 0
                    status_code = row.get("status_code")
                    if isinstance(status_code, int):
                        if status_code in {200, 204}:
                            adjust += 6
                        elif status_code in {301, 302}:
                            adjust += 4
                        elif status_code in {401, 403}:
                            adjust += 3
                        elif status_code >= 500:
                            adjust -= 3
                    error_text = str(row.get("error", "")).lower()
                    if "timed out" in error_text or "timeout" in error_text:
                        adjust -= 10
                    if "max retries exceeded" in error_text:
                        adjust -= 6
                    if adjust:
                        host_score_adjust[host] = host_score_adjust.get(host, 0) + adjust

    if host_score_adjust:
        adjusted_rows: list[dict[str, Any]] = []
        for row in host_rows:
            host = str(row.get("host", "")).strip().lower()
            score = int(row.get("score", 0)) + host_score_adjust.get(host, 0)
            adjusted_rows.append({**row, "score": score})
        host_rows = sorted(adjusted_rows, key=lambda x: (x.get("score", 0), x.get("host", "")), reverse=True)

    method_hints_sets = {path: set(methods) for path, methods in path_method_hints.items()}
    endpoint_candidates = build_endpoint_candidates(
        host_rows,
        extra_property_paths=property_paths,
        full_api_urls=full_api_urls,
        path_method_hints=method_hints_sets,
        direct_candidates=direct_candidates,
    )
    return {
        "hosts": host_rows,
        "property_api_paths": property_paths,
        "full_api_urls": full_api_urls,
        "path_method_hints": path_method_hints,
        "direct_candidates": direct_candidates,
        "endpoint_candidates": endpoint_candidates,
        "scan_file_count": len(scan_files),
    }


def save_discovery_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
