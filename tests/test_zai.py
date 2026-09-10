from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx

from panel.models import Status
from panel.providers.zai import fetch_zai


def _quota_payload() -> dict:
    return {
        "code": 200,
        "msg": "Operation successful",
        "success": True,
        "data": {
            "level": "lite",
            "limits": [
                {
                    "type": "CREDIT_LIMIT",
                    "unit": 3,
                    "number": 5,
                    "usage": 2000,
                    "currentValue": 5,
                    "remaining": 1994,
                    "percentage": 1,
                    "nextResetTime": 1788751732633,
                },
                {
                    "type": "CREDIT_LIMIT",
                    "unit": 6,
                    "number": 1,
                    "usage": 10000,
                    "currentValue": 5,
                    "remaining": 9994,
                    "percentage": 1,
                    "nextResetTime": 1789336616997,
                },
            ],
        },
    }


def _client(payload: dict | None = None, status: int = 200) -> MagicMock:
    client = MagicMock(spec=httpx.Client)
    resp = MagicMock()
    resp.status_code = status
    if payload is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = payload
    client.get.return_value = resp
    return client


def test_fetch_zai_credit_windows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("Z_AI_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    home = tmp_path / ".zai"
    home.mkdir()
    (home / "api_key").write_text("test-key", encoding="utf-8")
    r = fetch_zai("zai-default", "Z.AI/lite", home, _client(_quota_payload()), 5.0)
    assert r.status == Status.LIVE
    assert r.plan == "Lite"
    labels = [w.label for w in r.windows]
    assert labels == ["5h", "7d"]
    assert r.windows[0].used_pct == 1.0
    assert r.windows[0].rem_pct == 99.0
    assert r.windows[0].reset_at
    assert r.windows[1].rem_pct == 99.0


def test_fetch_zai_no_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("Z_AI_API_KEY", raising=False)
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    r = fetch_zai(
        "zai-default", "Z.AI/lite", tmp_path, MagicMock(spec=httpx.Client), 5.0
    )
    assert r.status == Status.DEAD
    assert "no ZAI_API_KEY" in r.reason


def test_fetch_zai_auth(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "bad")
    r = fetch_zai("zai-env", "Z.AI/env", tmp_path, _client({}, status=401), 5.0)
    assert r.status == Status.AUTH
