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
    monkeypatch.setattr(
        aplus_desktop,
        "load_aplus_cookies",
        lambda **_: {"lianjia_ssid": "demo-token"},
    )
    monkeypatch.setattr(aplus_desktop.requests, "Session", _FakeSession)

    report_path = tmp_path / "aplus_auto_probe_result.json"
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
