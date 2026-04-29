from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from property_workflow.config import resolve_base_path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ModuleNotFoundError:  # pragma: no cover - handled at runtime
    AESGCM = None  # type: ignore[assignment]


DEFAULT_PROBE_RESPONSE_PATHS = [
    "data.list",
    "data.rows",
    "data.records",
    "data.result.list",
    "result.list",
    "list",
    "rows",
    "records",
]

DEFAULT_PROBE_CANDIDATES = [
    {
        "endpoint": "https://xinfang.a.ke.com/api/deal/list",
        "method": "POST",
        "page_param": "pageNo",
        "page_size_param": "pageSize",
        "page_in": "body",
    },
    {
        "endpoint": "https://xinfang.a.ke.com/api/deal/list",
        "method": "GET",
        "page_param": "pageNo",
        "page_size_param": "pageSize",
        "page_in": "params",
    },
    {
        "endpoint": "https://xinfang.a.ke.com/api/deal/historyList",
        "method": "GET",
        "page_param": "pageNo",
        "page_size_param": "pageSize",
        "page_in": "params",
    },
    {
        "endpoint": "https://xinfang.a.ke.com/api/wolverine/houseFocus/queryHouseList",
        "method": "GET",
        "page_param": "pageNo",
        "page_size_param": "pageSize",
        "page_in": "params",
    },
    {
        "endpoint": "https://xinfang.a.ke.com/api/wolverine/houseFocus/queryHouseList",
        "method": "POST",
        "page_param": "pageNo",
        "page_size_param": "pageSize",
        "page_in": "body",
    },
    {
        "endpoint": "https://house.link.lianjia.com/api/deal/list",
        "method": "POST",
        "page_param": "pageNo",
        "page_size_param": "pageSize",
        "page_in": "body",
    },
    {
        "endpoint": "https://house.link.lianjia.com/api/deal/list",
        "method": "GET",
        "page_param": "pageNo",
        "page_size_param": "pageSize",
        "page_in": "params",
    },
    {
        "endpoint": "https://house.link.lianjia.com/search/searchQueryNew",
        "method": "GET",
        "page_param": "currentPage",
        "page_size_param": "",
        "page_in": "params",
        "base_params": {
            "del_type": "1",
            "vertical": "gdiv_mt",
            "tabSort": "default",
            "sort": "period1_desc_createtime_desc",
            "season": "",
            "riskLabelAction": "0",
            "riskLabelPerson": "0",
            "riskProtectMainHouse": "0",
            "maskAllHouse": "false",
            "punish": "false",
            "level": "0",
            "ucid": "",
            "timeLocal": "",
            "alertTitle": "",
            "alertContent": "",
            "algorithmPunishType": "0",
            "buttonVoList": "",
            "evtId": "",
            "punishCode": "500100000004",
            "riskStrategy": "",
            "riskStrategyInfo": "",
        },
    },
    {
        "endpoint": "https://house.link.lianjia.com/pc/risk/getRiskInfoV3",
        "method": "GET",
        "page_param": "currentPage",
        "page_size_param": "",
        "page_in": "params",
        "base_params": {
            "del_type": "1",
            "delType": "1",
            "riskType": "1001001005",
            "vertical": "gdiv_mt",
            "tabSort": "default",
            "sort": "period1_desc_createtime_desc",
        },
    },
]

SESSION_TOKEN_PREFIX_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_\-*=+/:.]{5,127})")


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


def _extract_path(payload: Any, path: str) -> Any:
    current = payload
    for token in path.split("."):
        token = token.strip()
        if not token:
            continue
        if isinstance(current, dict):
            current = current.get(token)
            continue
        if isinstance(current, list) and token.isdigit():
            index = int(token)
            if 0 <= index < len(current):
                current = current[index]
                continue
        return None
    return current


def _extract_first(payload: Any, selectors: str | list[str] | None) -> Any:
    if selectors is None:
        return None
    if isinstance(selectors, str):
        return _extract_path(payload, selectors)
    for selector in selectors:
        value = _extract_path(payload, selector)
        if value is not None and value != "":
            return value
    return None


def _to_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_safe_text(item) for item in value if _safe_text(item)]
    if isinstance(value, str):
        raw = value.replace(";", ",").replace("|", ",")
        return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    text = _safe_text(value)
    return [text] if text else []


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_decrypt(ciphertext: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("DPAPI is only available on Windows.")
    if not ciphertext:
        return b""

    buffer_in = ctypes.create_string_buffer(ciphertext, len(ciphertext))
    blob_in = _DataBlob(len(ciphertext), ctypes.cast(buffer_in, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()

    result = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    )
    if not result:
        raise OSError("CryptUnprotectData failed.")

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _load_master_key(local_state_path: Path | None) -> bytes | None:
    if not local_state_path or not local_state_path.exists():
        return None
    try:
        payload = json.loads(local_state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    encrypted_key = payload.get("os_crypt", {}).get("encrypted_key")
    if not encrypted_key:
        return None
    key_bytes = base64.b64decode(encrypted_key)
    if key_bytes.startswith(b"DPAPI"):
        key_bytes = key_bytes[5:]
    try:
        return _dpapi_decrypt(key_bytes)
    except OSError:
        return None


def _decrypt_chromium_cookie(encrypted_value: bytes, master_key: bytes | None) -> str:
    if not encrypted_value:
        return ""
    if encrypted_value.startswith((b"v10", b"v11")) and master_key and AESGCM is not None:
        nonce = encrypted_value[3:15]
        encrypted_payload = encrypted_value[15:]
        try:
            plain = AESGCM(master_key).decrypt(nonce, encrypted_payload, None)
            return plain.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    try:
        plain = _dpapi_decrypt(encrypted_value)
        return plain.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def load_aplus_cookies(
    cookie_db_path: Path,
    local_state_path: Path | None,
    cookie_domains: list[str] | None = None,
) -> dict[str, str]:
    rows = load_aplus_cookie_entries(
        cookie_db_path=cookie_db_path,
        local_state_path=local_state_path,
        cookie_domains=cookie_domains,
    )
    cookies: dict[str, str] = {}
    for row in rows:
        name = _safe_text(row.get("name"))
        value = _safe_text(row.get("value"))
        if name and value:
            cookies[name] = value
    return cookies


def load_aplus_cookie_entries(
    cookie_db_path: Path,
    local_state_path: Path | None,
    cookie_domains: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not cookie_db_path.exists():
        raise FileNotFoundError(f"Cookie DB not found: {cookie_db_path}")

    domains = cookie_domains or [".ke.com", ".lianjia.com", "app.a.ke.com", "saas.a.ke.com"]
    master_key = _load_master_key(local_state_path)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        temp_db_path = Path(tmp.name)
    shutil.copy2(cookie_db_path, temp_db_path)

    rows: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(temp_db_path))
        try:
            cur = conn.cursor()
            cur.execute("SELECT host_key, name, path, is_secure, value, encrypted_value FROM cookies")
            for host_key, name, path, is_secure, value, encrypted_value in cur.fetchall():
                host = _safe_text(host_key).lower()
                if domains and not any(host.endswith(d.lower()) for d in domains):
                    continue
                cookie_name = _safe_text(name)
                if not cookie_name:
                    continue

                cookie_value = _safe_text(value)
                if not cookie_value and isinstance(encrypted_value, bytes):
                    cookie_value = _decrypt_chromium_cookie(encrypted_value, master_key)
                if cookie_value:
                    rows.append(
                        {
                            "domain": host,
                            "name": cookie_name,
                            "value": cookie_value,
                            "path": _safe_text(path, "/") or "/",
                            "secure": bool(is_secure),
                        }
                    )
        finally:
            conn.close()
    finally:
        try:
            temp_db_path.unlink(missing_ok=True)
        except OSError:
            pass
    return rows


def apply_aplus_cookie_entries(
    session: requests.Session,
    cookie_entries: list[dict[str, Any]],
) -> None:
    for item in cookie_entries:
        name = _safe_text(item.get("name"))
        value = _safe_text(item.get("value"))
        if not name or not value:
            continue
        domain = _safe_text(item.get("domain"))
        path = _safe_text(item.get("path"), "/") or "/"
        kwargs: dict[str, Any] = {"path": path}
        if domain:
            kwargs["domain"] = domain
        session.cookies.set(name, value, **kwargs)


@dataclass
class DesktopAplusSettings:
    enabled: bool = False
    cookie_db_path: str = str(Path.home() / "AppData/Roaming/A+/Cookies")
    local_state_path: str = str(Path.home() / "AppData/Roaming/A+/Local State")
    runtime_root: str = "runtime"
    cookie_domains: list[str] = field(
        default_factory=lambda: [".ke.com", ".lianjia.com", "app.a.ke.com", "saas.a.ke.com"]
    )
    request_timeout_seconds: int = 20
    list_method: str = "GET"
    list_endpoint: str = ""
    list_base_params: dict[str, Any] = field(default_factory=dict)
    list_json_body: dict[str, Any] = field(default_factory=dict)
    list_headers: dict[str, str] = field(default_factory=dict)
    list_page_param: str = "page"
    list_page_size_param: str = "pageSize"
    list_page_in: str = "params"
    list_page_size_in: str = "params"
    list_start_page: int = 1
    list_page_size: int = 30
    list_max_pages: int = 30
    list_response_path: str | list[str] = "data.list"
    total_price_unit: str = "wan"
    detail_url_template: str = ""
    field_mapping: dict[str, str | list[str]] = field(default_factory=dict)
    auto_probe_enabled: bool = True
    auto_probe_candidates: list[dict[str, Any]] = field(default_factory=list)
    auto_probe_output_path: str = "aplus_auto_probe_result.json"
    auto_probe_discovery_path: str = "aplus_endpoint_discovery.json"
    auto_probe_max_candidates: int = 30
    auto_probe_request_timeout_seconds: int = 5
    auto_probe_max_per_host: int = 10
    dt_link_headers_enabled: bool = True
    dt_link_app_root: str = str(Path.home() / "AppData/Roaming/A+/resources/app")
    dt_link_user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Electron/22.0.0 asaas"
    dt_link_node_timeout_seconds: int = 12
    probe_session_tokens_enabled: bool = True
    probe_session_tokens_path: str = "session_host_tokens.json"
    probe_dt_header_names: list[str] = field(default_factory=lambda: ["dtSessionId"])
    probe_risk_header_names: list[str] = field(default_factory=lambda: ["risk_uuid"])
    sso_seed_enabled: bool = True
    sso_seed_hosts: list[str] = field(default_factory=list)
    sso_seed_timeout_seconds: int = 12
    cdp_capture_fallback_enabled: bool = True
    cdp_capture_path: str = "aplus_click_capture.json"
    cdp_capture_response_min_dict_rows: int = 5

    @classmethod
    def from_options(cls, options: dict[str, Any] | None) -> "DesktopAplusSettings":
        config = options or {}
        payload = config.get("desktop_aplus") or {}
        if not isinstance(payload, dict):
            payload = {}
        data = {**payload}
        base_paths = config.get("base_paths") or {}
        if isinstance(base_paths, dict):
            aplus_root_text = str(base_paths.get("aplus_root", "")).strip()
            if aplus_root_text:
                aplus_root = Path(aplus_root_text)
                if not str(data.get("cookie_db_path", "")).strip():
                    data["cookie_db_path"] = str((aplus_root / "Cookies").resolve())
                if not str(data.get("local_state_path", "")).strip():
                    data["local_state_path"] = str((aplus_root / "Local State").resolve())
                if not str(data.get("dt_link_app_root", "")).strip():
                    data["dt_link_app_root"] = str((aplus_root / "resources" / "app").resolve())
            data["runtime_root"] = str(resolve_base_path(config, "runtime_root", "runtime"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _resolve_output_path(settings: DesktopAplusSettings, path_text: str) -> Path:
    target = Path(path_text)
    if target.is_absolute():
        return target
    runtime_root = Path(_safe_text(settings.runtime_root, "runtime")).expanduser()
    if not runtime_root.is_absolute():
        runtime_root = (Path.cwd() / runtime_root).resolve()
    relative_text = str(target).replace("\\", "/")
    if relative_text.startswith("runtime/"):
        relative_text = relative_text[len("runtime/") :]
    if relative_text == "runtime":
        relative_text = ""
    return (runtime_root / relative_text).resolve()


def _to_selector_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        selector = value.strip()
        return [selector] if selector else []
    selectors: list[str] = []
    for item in value:
        selector = _safe_text(item)
        if selector:
            selectors.append(selector)
    return selectors


def _sanitize_session_token(value: Any) -> str:
    raw = _safe_text(value)
    if not raw:
        return ""
    if "map-" in raw:
        raw = raw.split("map-", 1)[0]
    raw = "".join(ch for ch in raw if 32 <= ord(ch) <= 126).strip()
    if not raw:
        return ""
    match = SESSION_TOKEN_PREFIX_PATTERN.match(raw)
    if match:
        raw = match.group(1)
    return raw if len(raw) >= 8 else ""


def _normalize_host_key(value: Any) -> str:
    host = _safe_text(value).lower()
    if not host:
        return ""
    if "://" in host:
        host = urlparse(host).netloc.lower()
    host = host.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].split(":", 1)[0]
    return host.lstrip(".")


def _load_session_host_probe_headers(settings: DesktopAplusSettings) -> dict[str, dict[str, str]]:
    if not settings.probe_session_tokens_enabled:
        return {}
    tokens_path = _resolve_output_path(settings, settings.probe_session_tokens_path)
    if not tokens_path.exists():
        return {}
    try:
        payload = json.loads(tokens_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    host_data = payload.get("host_data")
    if not isinstance(host_data, dict):
        return {}

    dt_header_names = [_safe_text(item) for item in settings.probe_dt_header_names if _safe_text(item)]
    risk_header_names = [_safe_text(item) for item in settings.probe_risk_header_names if _safe_text(item)]
    if not dt_header_names and not risk_header_names:
        return {}

    host_headers: dict[str, dict[str, str]] = {}
    for host_key, item in host_data.items():
        if not isinstance(item, dict):
            continue
        host = _normalize_host_key(host_key)
        if not host:
            continue
        dt_session_id = _sanitize_session_token(item.get("dtSessionId"))
        risk_uuid = _sanitize_session_token(item.get("risk_uuid"))
        headers: dict[str, str] = {}
        if dt_session_id:
            for header_name in dt_header_names:
                headers[header_name] = dt_session_id
        if risk_uuid:
            for header_name in risk_header_names:
                headers[header_name] = risk_uuid
        if headers:
            host_headers[host] = headers
    return host_headers


def _build_host_probe_headers(endpoint: str, host_headers: dict[str, dict[str, str]]) -> dict[str, str]:
    if not host_headers:
        return {}
    host = _normalize_host_key(urlparse(endpoint).netloc or endpoint)
    if not host:
        return {}
    if host in host_headers:
        return dict(host_headers[host])
    best_key = ""
    for key in host_headers:
        if host.endswith(f".{key}") and len(key) > len(best_key):
            best_key = key
    return dict(host_headers.get(best_key, {})) if best_key else {}


def _load_dt_link_headers(settings: DesktopAplusSettings) -> dict[str, str]:
    if not settings.dt_link_headers_enabled:
        return {}

    app_root = Path(_safe_text(settings.dt_link_app_root)).expanduser()
    if not app_root.exists():
        return {}

    script_path = app_root / "client" / "dist" / "index.js"
    if not script_path.exists():
        return {}

    node_script = r"""
const fs = require('fs');
const { createRequire } = require('module');
const appRoot = process.argv[1];
const uaText = process.argv[2] || 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Electron/22.0.0 asaas';
if (!appRoot) {
  console.log('{}');
  process.exit(0);
}
const appRequire = createRequire(appRoot + '/main.js');
const electronStub = {
  app: {
    getAppPath(){ return appRoot; },
    getPath(){ return appRoot.replace(/\\/resources\\/app$/, ''); },
    getName(){ return 'A+'; },
    commandLine: { appendSwitch(){} },
    requestSingleInstanceLock(){ return true; },
    on(){},
    whenReady(){ return Promise.resolve(); },
    quit(){},
    exit(){},
    setAsDefaultProtocolClient(){},
  },
  session: { defaultSession: { setUserAgent(){}, getUserAgent(){ return 'Mozilla/5.0'; }, webRequest: { onBeforeRequest(){}, onErrorOccurred(){} } } },
  protocol: {},
  BrowserWindow: function(){},
  ipcMain: {},
  crashReporter: { start(){} },
  globalShortcut: { register(){} },
  Menu: { buildFromTemplate(){ return {}; }, setApplicationMenu(){} },
  Notification: function(){},
  dialog: {},
  net: { request(){ return { on(){}, end(){} }; } },
};
function patchedRequire(name){
  if (name === 'electron') return electronStub;
  return appRequire(name);
}
try {
  let src = fs.readFileSync(appRoot + '/client/dist/index.js', 'utf8');
  if (!src.includes('n(n.s=36)')) {
    console.log('{}');
    process.exit(0);
  }
  src = src.replace('n(n.s=36)', 'n');
  const wrapped = `(function(module,exports,require){${src}; return module.exports;})`;
  const moduleObj = { exports: {} };
  const wreq = eval(wrapped)(moduleObj, moduleObj.exports, patchedRequire);
  const ua = wreq(10);
  ua.init(uaText);
  const token = wreq(17);
  const headers = token.getTokenHeader(false) || {};
  Object.keys(headers).forEach((k) => {
    headers[k] = String(headers[k]);
  });
  console.log(JSON.stringify(headers));
} catch (err) {
  console.log('{}');
}
"""

    try:
        run = subprocess.run(
            ["node", "-e", node_script, str(app_root), settings.dt_link_user_agent],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(settings.dt_link_node_timeout_seconds, 3),
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    payload_line = ""
    for raw in reversed((run.stdout or "").splitlines()):
        line = raw.strip()
        if line.startswith("{") and line.endswith("}"):
            payload_line = line
            break
    if not payload_line:
        return {}
    try:
        data = json.loads(payload_line)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}

    headers: dict[str, str] = {}
    for key, value in data.items():
        header_name = _safe_text(key)
        header_value = _safe_text(value)
        if header_name and header_value:
            headers[header_name] = header_value
    return headers


def _inject_page_values(
    params: dict[str, Any],
    body: dict[str, Any],
    page_key: str,
    page_size_key: str,
    page: int,
    page_size: int,
    page_in: str,
    page_size_in: str,
) -> None:
    page_target = body if page_in.lower() == "body" else params
    page_size_target = body if page_size_in.lower() == "body" else params
    if str(page_key).strip():
        page_target[page_key] = page
    if str(page_size_key).strip():
        page_size_target[page_size_key] = page_size


def _score_probe_endpoint(endpoint: str, method: str) -> int:
    parsed = urlparse(endpoint)
    path = parsed.path.lower()
    score = 0

    if "/api/deal/list" in path or "/api/house/list" in path:
        score += 260
    if "/search/searchquerynew" in path:
        score += 820
    if "/pc/risk/getriskinfov3" in path:
        score += 700
    if "queryhouselist" in path or "historylist" in path:
        score += 220
    if path.endswith("/api/list") or "/api/list" in path:
        score += 180
    if "/api/" in path and "/new/api/" not in path:
        score += 120
    if "/new/api/deal/" in path:
        score += 380
    if "/new/api/house/" in path:
        score += 340
    if "/new/api/" in path and any(keyword in path for keyword in ("deal", "house", "resblock", "query", "history")):
        score += 160
    if "list" in path:
        score += 80
    if method.upper() == "GET":
        score += 15

    if "welcome/ping" in path:
        score -= 320
    if any(
        keyword in path
        for keyword in (
            "houseinvalid",
            "cashcow",
            "/cfg/",
            "/source/",
            "housedel",
        )
    ):
        score -= 260
    if any(
        keyword in path
        for keyword in (
            "rejectagentdeal",
            "getinnercontract",
            "distributorcontracts",
        )
    ):
        score -= 420
    if any(
        keyword in path
        for keyword in (
            "maintenance",
            "resblock",
        )
    ):
        score -= 180
    if "/new/api/" in path and "list" not in path and not any(
        keyword in path for keyword in ("deal", "house", "resblock", "query", "history", "contract")
    ):
        score -= 100

    return score


def _build_probe_candidates(settings: DesktopAplusSettings) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []

    if settings.auto_probe_discovery_path:
        discovery_path = _resolve_output_path(settings, settings.auto_probe_discovery_path)
        if discovery_path.exists():
            try:
                discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                discovery = {}
            dynamic_candidates = discovery.get("endpoint_candidates", [])
            if isinstance(dynamic_candidates, list):
                payload.extend(dynamic_candidates)

    payload.extend(list(settings.auto_probe_candidates or DEFAULT_PROBE_CANDIDATES))

    ranked_payload: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        endpoint = _safe_text(raw.get("endpoint"))
        if not endpoint:
            continue
        method = _safe_text(raw.get("method"), settings.list_method or "GET").upper()
        item = dict(raw)
        item["method"] = method
        item["_probe_score"] = _score_probe_endpoint(endpoint, method)
        ranked_payload.append(item)
    ranked_payload.sort(key=lambda item: int(item.get("_probe_score", 0)), reverse=True)

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    host_count: dict[str, int] = {}
    for raw in ranked_payload:
        endpoint = _safe_text(raw.get("endpoint"))
        if not endpoint:
            continue
        method = _safe_text(raw.get("method"), settings.list_method or "GET").upper()
        host = urlparse(endpoint).netloc.lower()
        if host:
            if host_count.get(host, 0) >= settings.auto_probe_max_per_host:
                continue
        dedupe_key = (method, endpoint)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        page_in = _safe_text(raw.get("page_in"), "body" if method in {"POST", "PUT", "PATCH"} else "params")
        page_size_in = _safe_text(raw.get("page_size_in"), page_in)
        response_path = raw.get("response_path", settings.list_response_path)
        base_params = raw.get("base_params")
        json_body = raw.get("json_body")
        headers = raw.get("headers")
        candidates.append(
            {
                "endpoint": endpoint,
                "method": method,
                "page_param": _safe_text(raw.get("page_param"), settings.list_page_param),
                "page_size_param": _safe_text(raw.get("page_size_param"), settings.list_page_size_param),
                "page_in": page_in,
                "page_size_in": page_size_in,
                "base_params": base_params if isinstance(base_params, dict) else {},
                "json_body": json_body if isinstance(json_body, dict) else {},
                "headers": headers if isinstance(headers, dict) else {},
                "response_path": response_path,
            }
        )
        if host:
            host_count[host] = host_count.get(host, 0) + 1
        if len(candidates) >= settings.auto_probe_max_candidates:
            break
    return candidates


def _request_json(
    session: requests.Session,
    method: str,
    endpoint: str,
    headers: dict[str, str],
    params: dict[str, Any],
    body: dict[str, Any],
    timeout: int,
) -> tuple[requests.Response, Any]:
    request_kwargs: dict[str, Any] = {
        "method": method.upper(),
        "url": endpoint,
        "headers": headers,
        "timeout": timeout,
    }
    if params:
        request_kwargs["params"] = params
    if body and method.upper() in {"POST", "PUT", "PATCH"}:
        request_kwargs["json"] = body
    response = session.request(**request_kwargs)
    payload = response.json()
    return response, payload


def _build_sso_seed_hosts(settings: DesktopAplusSettings) -> list[str]:
    hosts: list[str] = []
    for value in settings.sso_seed_hosts:
        host = _safe_text(value).lower()
        if host and host not in hosts:
            hosts.append(host)

    # If caller did not specify host list, derive from current probe candidates.
    if not hosts:
        for candidate in _build_probe_candidates(settings):
            host = urlparse(str(candidate.get("endpoint", ""))).netloc.lower()
            if host and host not in hosts:
                hosts.append(host)
            if len(hosts) >= 8:
                break

    return hosts


def _seed_sso_sessions(
    session: requests.Session,
    hosts: list[str],
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for host in hosts:
        service_url = f"https://{host}/login"
        cas_url = f"https://login.ke.com/login?service={quote(service_url, safe=':/?=&')}"
        item: dict[str, Any] = {"host": host, "cas_url": cas_url}
        try:
            cas_resp = session.get(cas_url, timeout=timeout_seconds, allow_redirects=True)
            item["cas_status"] = cas_resp.status_code
            item["cas_final_url"] = cas_resp.url
        except requests.RequestException as exc:
            item["cas_error"] = str(exc)
            rows.append(item)
            continue

        try:
            home_resp = session.get(f"https://{host}/", timeout=timeout_seconds, allow_redirects=False)
            item["home_status"] = home_resp.status_code
            item["home_location"] = home_resp.headers.get("Location", "")
        except requests.RequestException as exc:
            item["home_error"] = str(exc)
        rows.append(item)
    return rows


def _auto_probe_list_config(
    session: requests.Session,
    settings: DesktopAplusSettings,
    host_probe_headers: dict[str, dict[str, str]] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any], Path]:
    candidates = _build_probe_candidates(settings)
    if not candidates:
        raise ValueError("desktop_aplus.auto_probe_candidates is empty")

    discovered: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = []
    report_path = _resolve_output_path(settings, settings.auto_probe_output_path)

    for candidate in candidates:
        params = dict(candidate["base_params"])
        body = dict(candidate["json_body"])
        _inject_page_values(
            params=params,
            body=body,
            page_key=candidate["page_param"],
            page_size_key=candidate["page_size_param"],
            page=settings.list_start_page,
            page_size=settings.list_page_size,
            page_in=candidate["page_in"],
            page_size_in=candidate["page_size_in"],
        )
        endpoint_host_headers = _build_host_probe_headers(candidate["endpoint"], host_probe_headers or {})
        headers = {
            **settings.list_headers,
            **candidate["headers"],
            **(extra_headers or {}),
            **endpoint_host_headers,
        }

        attempt: dict[str, Any] = {
            "method": candidate["method"],
            "url": candidate["endpoint"],
            "page_param": candidate["page_param"],
            "page_size_param": candidate["page_size_param"],
            "page_in": candidate["page_in"],
            "page_size_in": candidate["page_size_in"],
        }
        if endpoint_host_headers:
            attempt["host_probe_header_names"] = sorted(endpoint_host_headers.keys())

        try:
            request_kwargs: dict[str, Any] = {
                "method": candidate["method"].upper(),
                "url": candidate["endpoint"],
                "headers": headers,
                "timeout": settings.auto_probe_request_timeout_seconds,
            }
            if params:
                request_kwargs["params"] = params
            if body and candidate["method"].upper() in {"POST", "PUT", "PATCH"}:
                request_kwargs["json"] = body

            response = session.request(**request_kwargs)
            attempt["status"] = response.status_code
            attempt["final_url"] = response.url
            attempt["sample"] = response.text[:240]
            try:
                payload = response.json()
            except ValueError as exc:
                attempt["json_error"] = str(exc)
                attempts.append(attempt)
                continue
            if isinstance(payload, dict):
                attempt["json_keys"] = sorted(payload.keys())

            selectors = _to_selector_list(candidate["response_path"])
            selectors.extend(_to_selector_list(settings.list_response_path))
            selectors.extend(DEFAULT_PROBE_RESPONSE_PATHS)
            dedup_selectors: list[str] = []
            for selector in selectors:
                if selector and selector not in dedup_selectors:
                    dedup_selectors.append(selector)

            for selector in dedup_selectors:
                list_payload = _extract_first(payload, selector)
                if not isinstance(list_payload, list):
                    continue
                dict_count = len([item for item in list_payload if isinstance(item, dict)])
                attempt["matched_response_path"] = selector
                attempt["list_size"] = len(list_payload)
                attempt["dict_row_count"] = dict_count
                if dict_count > 0:
                    discovered = {
                        "endpoint": candidate["endpoint"],
                        "method": candidate["method"],
                        "page_param": candidate["page_param"],
                        "page_size_param": candidate["page_size_param"],
                        "page_in": candidate["page_in"],
                        "page_size_in": candidate["page_size_in"],
                        "base_params": candidate["base_params"],
                        "json_body": candidate["json_body"],
                        "headers": candidate["headers"],
                        "response_path": selector,
                    }
                    break
        except requests.RequestException as exc:
            attempt["error"] = str(exc)
        attempts.append(attempt)
        if discovered is not None:
            break

    report_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "success": discovered is not None,
        "resolved": discovered,
        "attempts": attempts,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if discovered is None:
        raise ValueError(f"desktop_aplus auto probe failed, see {report_path}")
    return discovered, report_path


def _map_row(
    raw: dict[str, Any],
    settings: DesktopAplusSettings,
    city: str,
    districts: list[str],
    index: int,
) -> dict[str, Any]:
    mapping = settings.field_mapping

    def pick(name: str, fallback: list[str]) -> Any:
        selector = mapping.get(name) if mapping else None
        return _extract_first(raw, selector if selector else fallback)

    listing_id = _safe_text(pick("listing_id", ["houseCode", "house_code", "houseId", "id"]))
    community = _safe_text(
        pick("community", ["communityName", "resblockName", "villageName", "buildingName", "xiaoqu"])
    )
    district = _safe_text(pick("district", ["districtName", "district", "bizcircleName"]), "")
    title = _safe_text(pick("title", ["title", "houseTitle", "name"]), "")
    layout = _safe_text(pick("layout", ["layout", "roomHall", "houseType"]), "")

    area_sqm = _safe_float(pick("area_sqm", ["area", "buildArea", "houseArea", "acreage"]))
    total_price_wan = _safe_float(
        pick("total_price_wan", ["totalPrice", "price", "showPrice", "listPrice"])
    )
    if settings.total_price_unit.lower() == "yuan":
        total_price_wan = round(total_price_wan / 10000, 4)

    listed_at = _safe_text(pick("listed_at", ["listedAt", "publishTime", "createTime", "updateTime"]))
    url = _safe_text(pick("url", ["url", "detailUrl", "houseUrl"]))
    tags = _to_tags(pick("tags", ["tags", "houseTags", "labelNames", "labels"]))

    if not district and districts:
        district = districts[index % len(districts)]
    if not title:
        title = f"{community}{layout}".strip() or f"beike_{listing_id or index}"
    if not community:
        community = title[:20] if title else "unknown"
    if not layout:
        layout = "unknown"
    if not listing_id:
        listing_id = f"aplus-{index:06d}"
    if not url and settings.detail_url_template:
        try:
            url = settings.detail_url_template.format(listing_id=listing_id)
        except KeyError:
            url = ""

    return {
        "listing_id": listing_id,
        "source": "beike",
        "city": city,
        "district": district or "unknown",
        "community": community,
        "title": title,
        "layout": layout,
        "area_sqm": area_sqm,
        "total_price_wan": total_price_wan,
        "listed_at": listed_at,
        "url": url,
        "tags": tags,
    }


def _is_business_capture_url(url: str) -> bool:
    lowered = _safe_text(url).lower()
    if not lowered:
        return False
    host = _safe_text(urlparse(lowered).netloc).lower()
    if host and any(
        host.endswith(item)
        for item in (
            "house.link.lianjia.com",
            "xinfang.a.ke.com",
            "deal.fang.lianjia.com",
            "linkconsole.fang.lianjia.com",
            "fang.link.lianjia.com",
            "haofang.lianjia.com",
            "yezhu.link.lianjia.com",
            "xiaoxi.link.lianjia.com",
        )
    ):
        return True
    return any(
        token in lowered
        for token in (
            "/search/",
            "/pc/risk/",
            "/layer/",
            "queryhouselist",
            "/api/deal/",
            "/api/house/",
            "resblock",
        )
    )


def _load_rows_from_cdp_capture(
    settings: DesktopAplusSettings,
    city: str,
    districts: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    if not settings.cdp_capture_fallback_enabled:
        return []
    capture_path = _resolve_output_path(settings, settings.cdp_capture_path)
    if not capture_path.exists():
        return []
    try:
        payload = json.loads(capture_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    responses = payload.get("responses", [])
    if not isinstance(responses, list):
        return []

    min_dict_rows = max(int(settings.cdp_capture_response_min_dict_rows), 1)
    best_rows: list[dict[str, Any]] = []
    best_score = -1

    for row in responses:
        if not isinstance(row, dict):
            continue
        url = _safe_text(row.get("url"))
        if not _is_business_capture_url(url):
            continue

        dict_count = int(row.get("dictRowCount", 0) or 0)
        if dict_count < min_dict_rows:
            continue

        list_rows_raw = row.get("listRows", [])
        list_rows = [item for item in list_rows_raw if isinstance(item, dict)] if isinstance(list_rows_raw, list) else []

        # Backward compatibility for old capture payloads without listRows.
        if not list_rows:
            body_sample = _safe_text(row.get("bodySample"))
            list_path = _safe_text(row.get("listPath"))
            if body_sample and list_path:
                try:
                    parsed = json.loads(body_sample)
                    extracted = _extract_first(parsed, list_path)
                    if isinstance(extracted, list):
                        list_rows = [item for item in extracted if isinstance(item, dict)]
                except json.JSONDecodeError:
                    pass
        if not list_rows:
            continue

        score = dict_count
        if "house.link.lianjia.com" in url.lower():
            score += 20
        if "/search/" in url.lower():
            score += 12
        if "/api/" in url.lower():
            score += 8
        if score <= best_score:
            continue
        best_score = score
        best_rows = list_rows

    if not best_rows:
        return []

    output: list[dict[str, Any]] = []
    for item in best_rows:
        output.append(_map_row(item, settings, city, districts, len(output) + 1))
        if len(output) >= limit:
            break
    return output


def collect_from_aplus_desktop(
    city: str,
    districts: list[str],
    limit: int,
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    settings = DesktopAplusSettings.from_options(options)
    if not settings.enabled:
        return []
    needs_probe = not settings.list_endpoint
    if needs_probe and not settings.auto_probe_enabled:
        raise ValueError(
            "desktop_aplus.list_endpoint is required when desktop_aplus.enabled=true "
            "or set desktop_aplus.auto_probe_enabled=true"
        )

    try:
        cookie_entries = load_aplus_cookie_entries(
            cookie_db_path=Path(settings.cookie_db_path),
            local_state_path=Path(settings.local_state_path) if settings.local_state_path else None,
            cookie_domains=settings.cookie_domains,
        )
    except FileNotFoundError as exc:
        if needs_probe:
            raise ValueError(
                "desktop_aplus.list_endpoint is empty and cookie DB is unavailable. "
                "Open A+ desktop and login first."
            ) from exc
        raise
    if not cookie_entries:
        if needs_probe:
            raise ValueError(
                "desktop_aplus.list_endpoint is empty and no A+ cookies found for auto probe. "
                "Please login in desktop app first."
            )
        raise RuntimeError("No valid A+ session cookies found. Please login in desktop app first.")

    session = requests.Session()
    apply_aplus_cookie_entries(session=session, cookie_entries=cookie_entries)
    dt_link_headers = _load_dt_link_headers(settings=settings)
    host_probe_headers = _load_session_host_probe_headers(settings=settings)
    if settings.sso_seed_enabled:
        seed_hosts = _build_sso_seed_hosts(settings)
        if seed_hosts:
            _seed_sso_sessions(
                session=session,
                hosts=seed_hosts,
                timeout_seconds=max(settings.sso_seed_timeout_seconds, 3),
            )

    if needs_probe:
        try:
            discovered, report_path = _auto_probe_list_config(
                session=session,
                settings=settings,
                host_probe_headers=host_probe_headers,
                extra_headers=dt_link_headers,
            )
            settings.list_endpoint = discovered["endpoint"]
            settings.list_method = discovered["method"]
            settings.list_page_param = discovered["page_param"]
            settings.list_page_size_param = discovered["page_size_param"]
            settings.list_page_in = discovered["page_in"]
            settings.list_page_size_in = discovered["page_size_in"]
            settings.list_response_path = discovered["response_path"]
            if not settings.list_base_params:
                settings.list_base_params = discovered["base_params"]
            if not settings.list_json_body:
                settings.list_json_body = discovered["json_body"]
            if discovered["headers"]:
                settings.list_headers = {**discovered["headers"], **settings.list_headers}
            print(f"[beike][desktop] auto probe success: {settings.list_method} {settings.list_endpoint}")
            print(f"[beike][desktop] auto probe report -> {report_path}")
        except Exception:
            fallback_rows = _load_rows_from_cdp_capture(
                settings=settings,
                city=city,
                districts=districts,
                limit=limit,
            )
            if fallback_rows:
                print(
                    "[beike][desktop] auto probe failed, "
                    f"fallback to CDP capture rows: {len(fallback_rows)}"
                )
                return fallback_rows
            raise

    rows: list[dict[str, Any]] = []
    method = settings.list_method.upper()
    static_headers = {
        **settings.list_headers,
        **dt_link_headers,
        **_build_host_probe_headers(settings.list_endpoint, host_probe_headers),
    }

    for page in range(settings.list_start_page, settings.list_start_page + settings.list_max_pages):
        params = dict(settings.list_base_params)
        body = dict(settings.list_json_body)
        _inject_page_values(
            params=params,
            body=body,
            page_key=settings.list_page_param,
            page_size_key=settings.list_page_size_param,
            page=page,
            page_size=settings.list_page_size,
            page_in=settings.list_page_in,
            page_size_in=settings.list_page_size_in,
        )

        response, payload = _request_json(
            session=session,
            method=method,
            endpoint=settings.list_endpoint,
            headers=static_headers,
            params=params,
            body=body,
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        list_payload = _extract_first(payload, settings.list_response_path)
        if not isinstance(list_payload, list):
            raise ValueError(
                "Could not parse list rows from response. "
                f"Check desktop_aplus.list_response_path={settings.list_response_path!r}"
            )
        if not list_payload:
            break

        for item in list_payload:
            if not isinstance(item, dict):
                continue
            rows.append(_map_row(item, settings, city, districts, len(rows) + 1))
            if len(rows) >= limit:
                return rows

        if len(list_payload) < settings.list_page_size:
            break

    return rows[:limit]
