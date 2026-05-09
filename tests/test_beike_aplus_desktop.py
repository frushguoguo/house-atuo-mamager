from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

import property_workflow.collectors.aplus_desktop as aplus_desktop
from property_workflow.collectors.aplus_desktop import DesktopAplusSettings, _map_row, collect_from_aplus_desktop
from property_workflow.collectors.beike import BeikeCollector


class _FakeResponse:
    def __init__(self, status_code: int, url: str, payload: Any) -> None:
        self.status_code = status_code
        self.url = url
        self._payload = payload
        self.headers: dict[str, str] = {}
        self.text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)

    def json(self) -> Any:
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}", response=self)


class _FakeSession:
    def __init__(self) -> None:
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self.request(method="GET", url=url, **kwargs)

    def request(self, **kwargs: Any) -> _FakeResponse:
        method = str(kwargs.get("method", "GET")).upper()
        url = str(kwargs.get("url", ""))
        if method == "POST" and url == "https://xinfang.a.ke.com/api/deal/list":
            return _FakeResponse(
                status_code=200,
                url=url,
                payload={
                    "data": {
                        "list": [
                            {
                                "houseCode": "H001",
                                "communityName": "Demo Community",
                                "districtName": "pudong",
                                "houseType": "2-1-1",
                                "buildArea": "90.5",
                                "totalPrice": "350",
                            }
                        ]
                    }
                },
            )
        return _FakeResponse(status_code=404, url=url, payload={"error": "not found"})


def test_map_row_uses_fallback_fields() -> None:
    settings = DesktopAplusSettings(
        enabled=True,
        field_mapping={
            "listing_id": ["houseCode"],
            "community": ["communityName"],
            "district": ["districtName"],
            "layout": ["houseType"],
            "area_sqm": ["buildArea"],
            "total_price_wan": ["totalPrice"],
            "tags": ["labels"],
        },
    )
    raw = {
        "houseCode": "106127111111",
        "communityName": "Demo Community",
        "districtName": "new-district",
        "houseType": "3-2-1-2",
        "buildArea": "109.2 sqm",
        "totalPrice": "54.5",
        "labels": "elevator,vr",
    }

    row = _map_row(raw, settings, city="urumqi", districts=["xinqu"], index=1)

    assert row["listing_id"] == "106127111111"
    assert row["community"] == "Demo Community"
    assert row["district"] == "new-district"
    assert row["area_sqm"] == 109.2
    assert row["total_price_wan"] == 54.5
    assert row["tags"] == ["elevator", "vr"]


def test_beike_collector_fallback_to_synthetic_when_desktop_collect_fails() -> None:
    collector = BeikeCollector()
    rows = collector.collect(
        city="shanghai",
        districts=["pudong"],
        limit=5,
        options={
            "desktop_aplus": {
                "enabled": True,
                "fallback_to_synthetic": True,
                "list_endpoint": "",
                "auto_probe_enabled": False,
            }
        },
    )
    assert len(rows) == 5
    assert all(row["source"] == "beike" for row in rows)


def test_beike_collector_raises_when_desktop_collect_fails_without_fallback() -> None:
    collector = BeikeCollector()
    with pytest.raises(ValueError):
        collector.collect(
            city="shanghai",
            districts=["pudong"],
            limit=5,
            options={
                "desktop_aplus": {
                    "enabled": True,
                    "fallback_to_synthetic": False,
                    "list_endpoint": "",
                    "auto_probe_enabled": False,
                }
            },
        )


def test_collect_from_aplus_desktop_auto_probe_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "aplus_auto_probe_result.json"

    def _fake_probe(**_: Any) -> tuple[dict[str, Any], Path]:
        report_path.write_text(
            json.dumps({"success": True, "resolved": {"endpoint": "https://xinfang.a.ke.com/api/deal/list"}}),
            encoding="utf-8",
        )
        return (
            {
                "endpoint": "https://xinfang.a.ke.com/api/deal/list",
                "method": "POST",
                "page_param": "pageNo",
                "page_size_param": "pageSize",
                "page_in": "body",
                "page_size_in": "body",
                "response_path": "data.list",
                "base_params": {},
                "json_body": {},
                "headers": {},
            },
            report_path,
        )

    monkeypatch.setattr(
        aplus_desktop,
        "load_aplus_cookie_entries",
        lambda **_: [{"name": "lianjia_ssid", "value": "demo-token", "domain": ".lianjia.com"}],
    )
    monkeypatch.setattr(
        aplus_desktop,
        "_auto_probe_list_config",
        _fake_probe,
    )
    monkeypatch.setattr(aplus_desktop.requests, "Session", _FakeSession)
    rows = collect_from_aplus_desktop(
        city="shanghai",
        districts=["pudong"],
        limit=5,
        options={
            "desktop_aplus": {
                "enabled": True,
                "list_endpoint": "",
                "auto_probe_enabled": True,
                "auto_probe_output_path": str(report_path),
                "list_max_pages": 1,
                "list_page_size": 30,
            }
        },
    )

    assert len(rows) == 1
    assert rows[0]["listing_id"] == "H001"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["success"] is True


def test_collect_from_aplus_desktop_probe_fallback_is_reported_as_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        aplus_desktop,
        "load_aplus_cookie_entries",
        lambda **_: [{"name": "lianjia_ssid", "value": "demo-token", "domain": ".lianjia.com"}],
    )
    monkeypatch.setattr(
        aplus_desktop,
        "_auto_probe_list_config",
        lambda **_: (_ for _ in ()).throw(ValueError("auto probe failed")),
    )

    capture_path = tmp_path / "aplus_click_capture.json"
    capture_payload = {
        "responses": [
            {
                "url": "https://lease-pz.link.lianjia.com/api/houselist/search/pc/list",
                "method": "POST",
                "listPath": "data.list",
                "dictRowCount": 2,
                "listRows": [
                    {"houseCode": "H001", "communityName": "Demo A", "districtName": "pudong", "houseType": "2-1-1", "buildArea": 85, "totalPrice": 420},
                    {"houseCode": "H002", "communityName": "Demo B", "districtName": "pudong", "houseType": "3-1-1", "buildArea": 95, "totalPrice": 520},
                ],
            }
        ]
    }
    capture_path.write_text(json.dumps(capture_payload, ensure_ascii=False), encoding="utf-8")
    report_path = tmp_path / "aplus_auto_probe_result.json"

    rows = collect_from_aplus_desktop(
        city="shanghai",
        districts=["pudong"],
        limit=10,
        options={
            "desktop_aplus": {
                "enabled": True,
                "list_endpoint": "",
                "auto_probe_enabled": True,
                "auto_probe_output_path": str(report_path),
                "cdp_capture_path": str(capture_path),
                "cdp_capture_response_min_dict_rows": 1,
                "sso_seed_enabled": False,
                "dt_link_headers_enabled": False,
            }
        },
    )
    assert len(rows) == 2

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["success"] is True
    assert report["mode"] == "cdp_fallback"
    assert report["fallback"]["status"] == "success"
    assert report["fallback"]["row_count"] == len(rows)


def test_collect_from_aplus_desktop_lease_pz_pagination_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    class _LeaseSession(_FakeSession):
        def request(self, **kwargs: Any) -> _FakeResponse:
            method = str(kwargs.get("method", "GET")).upper()
            url = str(kwargs.get("url", ""))
            if method != "GET" or "lease-pz.link.lianjia.com" not in url:
                return _FakeResponse(status_code=404, url=url, payload={"error": "not found"})
            params = kwargs.get("params") or {}
            page = int(params.get("currentPage", 1))
            payload_by_page = {
                1: {
                    "data": {
                        "list": [
                            {"houseCode": "H001", "communityName": "A", "districtName": "pudong", "houseType": "2-1-1", "buildArea": 80, "totalPrice": 400},
                            {"houseCode": "H002", "communityName": "B", "districtName": "pudong", "houseType": "2-1-1", "buildArea": 90, "totalPrice": 500},
                        ]
                    }
                },
                2: {
                    "data": {
                        "list": [
                            {"houseCode": "H002", "communityName": "B", "districtName": "pudong", "houseType": "2-1-1", "buildArea": 90, "totalPrice": 500},
                            {"houseCode": "H003", "communityName": "C", "districtName": "pudong", "houseType": "3-1-1", "buildArea": 100, "totalPrice": 600},
                        ]
                    }
                },
                3: {"data": {"list": []}},
            }
            return _FakeResponse(status_code=200, url=url, payload=payload_by_page.get(page, {"data": {"list": []}}))

    monkeypatch.setattr(
        aplus_desktop,
        "load_aplus_cookie_entries",
        lambda **_: [{"name": "lianjia_ssid", "value": "demo-token", "domain": ".lianjia.com"}],
    )
    monkeypatch.setattr(aplus_desktop.requests, "Session", _LeaseSession)

    rows = collect_from_aplus_desktop(
        city="shanghai",
        districts=["pudong"],
        limit=10,
        options={
            "desktop_aplus": {
                "enabled": True,
                "auto_probe_enabled": False,
                "list_endpoint": "https://lease-pz.link.lianjia.com/api/houselist/search/pc/list",
                "list_method": "GET",
                "list_page_param": "currentPage",
                "list_page_size_param": "pageSize",
                "list_page_in": "params",
                "list_page_size_in": "params",
                "list_response_path": "data.list",
                "list_page_size": 2,
                "list_max_pages": 5,
                "sso_seed_enabled": False,
                "dt_link_headers_enabled": False,
            }
        },
    )
    assert [row["listing_id"] for row in rows] == ["H001", "H002", "H003"]
