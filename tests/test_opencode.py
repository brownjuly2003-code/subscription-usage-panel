from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx

from panel.config import ProfileCfg
from panel.fetch import fetch_one
from panel.html_dash import render_dashboard_html
from panel.models import Balance, ProfileResult, Status
from panel.providers.opencode import fetch_opencode
from panel.render import render_frame
from panel.schema import build_payload, exit_code_from_payload


def _resp(status: int, payload: dict | None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    if payload is None:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = payload
    return r


def _client(billing: MagicMock, summary: MagicMock | None = None) -> MagicMock:
    client = MagicMock(spec=httpx.Client)

    def get(url, **kwargs):
        if url.endswith("/billing/status"):
            return billing
        if url.endswith("/usage/summary"):
            assert kwargs.get("params") == {"range": "30d"}
            return summary or _resp(500, None)
        raise AssertionError(url)

    client.get.side_effect = get
    return client


BILLING = {
    "billingMode": "prepaid",
    "mode": "pay-as-you-go",
    "balanceMicroCents": "2770336463",
    "creditLimitMicroCents": None,
    "availableMicroCents": "2770336463",
}


def test_balance_from_micro_cents_with_30d_spend(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    key_file = tmp_path / "key.txt"
    key_file.write_text("  zen-key\n", encoding="utf-8")
    client = _client(
        _resp(200, BILLING), _resp(200, {"totalCostMicroCents": "2229663537"})
    )

    r = fetch_opencode("oc", "DEEPSEEK/opencode", tmp_path, client, 5.0, key_file)

    assert r.status == Status.LIVE
    assert r.balance is not None
    assert abs(r.balance.amount - 27.70336463) < 1e-9
    assert abs(r.balance.spent_30d - 22.29663537) < 1e-9
    assert r.plan == "Zen pay-as-you-go"
    assert r.windows == []
    auth = client.get.call_args_list[0].kwargs["headers"]
    assert auth["Authorization"] == "Bearer zen-key"
    assert "python" not in auth["User-Agent"].lower()


def test_spend_failure_keeps_balance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "env-key")
    r = fetch_opencode("oc", "OC", tmp_path, _client(_resp(200, BILLING)), 5.0)
    assert r.status == Status.LIVE
    assert r.balance.spent_30d is None
    assert r.meta["key_source"] == "env"


def test_key_file_wins_over_env_and_auth_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "env-key")
    (tmp_path / "auth.json").write_text(
        json.dumps({"opencode": {"type": "api", "key": "cli-key"}}), encoding="utf-8"
    )
    key_file = tmp_path / "k.txt"
    key_file.write_text("file-key", encoding="utf-8")
    client = _client(_resp(200, BILLING))
    fetch_opencode("oc", "OC", tmp_path, client, 5.0, key_file)
    headers = client.get.call_args_list[0].kwargs["headers"]
    assert headers["Authorization"] == "Bearer file-key"


def test_cli_auth_json_key_is_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    (tmp_path / "auth.json").write_text(
        json.dumps({"opencode": {"type": "api", "key": "cli-key"}}), encoding="utf-8"
    )
    client = _client(_resp(200, BILLING))
    r = fetch_opencode("oc", "OC", tmp_path, client, 5.0)
    assert r.meta["key_source"] == "auth.json"


def test_expired_key_is_auth_not_zero_balance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "old")
    body = {"code": "api_key_expired", "message": "This API key has expired."}
    r = fetch_opencode("oc", "OC", tmp_path, _client(_resp(401, body)), 5.0)
    assert r.status == Status.AUTH
    assert r.balance is None
    assert "истёк" in r.reason


def test_missing_key_file_is_dead(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "env-key")
    client = MagicMock(spec=httpx.Client)
    r = fetch_opencode("oc", "OC", tmp_path, client, 5.0, tmp_path / "nope.txt")
    assert r.status == Status.DEAD
    client.get.assert_not_called()


def test_bad_balance_field_is_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "k")
    r = fetch_opencode(
        "oc", "OC", tmp_path, _client(_resp(200, {"mode": "pay-as-you-go"})), 5.0
    )
    assert r.status == Status.ERROR
    assert r.balance is None


def test_fetch_one_passes_key_file_only_where_supported(tmp_path: Path) -> None:
    client = MagicMock(spec=httpx.Client)
    p = ProfileCfg("c", "claude", "C", tmp_path, key_file=tmp_path / "k.txt")
    r = fetch_one(p, client, 1.0)
    assert r.status == Status.ERROR
    assert "key_file" in r.reason
    client.get.assert_not_called()


def _balance_result(amount: float, spent: float | None = 22.3) -> ProfileResult:
    return ProfileResult(
        id="opencode-zen",
        family="opencode",
        label="DEEPSEEK/opencode",
        status=Status.LIVE,
        plan="Zen pay-as-you-go",
        balance=Balance(amount=amount, spent_30d=spent),
    )


def test_balance_card_shows_money_not_percent() -> None:
    html = render_dashboard_html([_balance_result(27.7034)], 10.0, theme="dark")
    start = html.find('data-label="deepseek/opencode"')
    assert start > 0
    body = html[start : html.find("</div>\n      </div>", start)]
    assert 'data-kind="balance"' in body
    assert "$27.70" in body
    assert "$22.30" in body
    assert "%" not in body
    assert 'id="offlinePanel"' not in html


def test_low_balance_raises_alert_and_exit_code() -> None:
    payload = build_payload([_balance_result(0.75, None)], 1.0)
    entry = payload["profiles"][0]
    assert entry["balance"] == {"amount": 0.75, "currency": "USD", "spent_30d": None}
    assert entry["urgency"] == "critical"
    assert payload["alerts"][0]["message"] == "DEEPSEEK/opencode: $0.75 left"
    assert exit_code_from_payload(payload) == 2

    ok = build_payload([_balance_result(27.7)], 1.0)
    assert ok["alerts"] == []
    assert ok["profiles"][0]["urgency"] == "ok"
    assert exit_code_from_payload(ok) == 0


def test_terminal_line_shows_balance(tmp_path: Path) -> None:
    from panel.config import AppConfig

    out = render_frame([_balance_result(27.7)], AppConfig(), 1.0)
    assert "$27.70" in out
    assert "30d $22.30" in out
