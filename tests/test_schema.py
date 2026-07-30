from panel.models import ProfileResult, Status, Window
from panel.schema import SCHEMA_VERSION, build_payload, exit_code_from_payload


def test_schema_version_and_primary():
    r = ProfileResult(
        id="x",
        family="codex",
        label="CODEX/work",
        status=Status.LIVE,
        windows=[
            Window("7d", used_pct=90, rem_pct=10, reset="1d", reset_at="2026-08-01 12:00"),
            Window("5h", used_pct=20, rem_pct=80, reset="2h", reset_at="2026-07-30 15:00"),
        ],
    )
    p = build_payload([r], 12.5)
    assert p["schemaVersion"] == SCHEMA_VERSION
    assert p["summary"]["profiles_live"] == 1
    assert p["profiles"][0]["primary"]["remaining_pct"] == 10
    assert p["profiles"][0]["urgency"] == "critical"
    assert p["summary"]["alerts_critical"] == 1
    assert exit_code_from_payload(p) == 2


def test_exit_warn():
    r = ProfileResult(
        id="g",
        family="grok",
        label="GROK/work",
        status=Status.LIVE,
        windows=[Window("7d", used_pct=85, rem_pct=15)],
    )
    p = build_payload([r], 1)
    assert p["profiles"][0]["urgency"] == "warn"
    assert exit_code_from_payload(p) == 1


def test_exit_no_live():
    r = ProfileResult(
        id="c",
        family="claude",
        label="CLAUDE/x",
        status=Status.AUTH,
        reason="login",
    )
    p = build_payload([r], 1)
    assert exit_code_from_payload(p) == 3


def test_window_human_period():
    r = ProfileResult(
        id="g",
        family="grok",
        label="GROK/p",
        status=Status.LIVE,
        windows=[Window("7d", used_pct=10, rem_pct=90)],
    )
    p = build_payload([r], 1)
    assert p["profiles"][0]["primary"]["period"] == "week"
