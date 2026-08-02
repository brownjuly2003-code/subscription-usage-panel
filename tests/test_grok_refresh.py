"""Grok OIDC silent refresh (auth.json rotation + lock + peer race)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx

from panel.models import Status
from panel.providers import grok as grok_mod


def _fake_jwt(exp: float) -> str:
    import base64

    def b64(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{b64({'alg':'none'})}.{b64({'exp': exp})}.sig"


def _write_auth(home: Path, *, exp: float, refresh: str = "rt-old") -> None:
    home.mkdir(parents=True, exist_ok=True)
    entry = {
        "key": _fake_jwt(exp),
        "email": "t@example.com",
        "team_id": "team-1",
        "refresh_token": refresh,
        "oidc_issuer": "https://auth.x.ai",
        "oidc_client_id": grok_mod.DEFAULT_OIDC_CLIENT_ID,
        "expires_at": "2099-01-01T00:00:00.000000Z",
    }
    data = {f"https://auth.x.ai::{grok_mod.DEFAULT_OIDC_CLIENT_ID}": entry}
    (home / "auth.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def test_refresh_when_jwt_expired(tmp_path: Path) -> None:
    home = tmp_path / ".grok"
    _write_auth(home, exp=time.time() - 10)

    new_access = _fake_jwt(time.time() + 3600)
    client = MagicMock(spec=httpx.Client)

    def post(url, **kwargs):
        if "oauth2/token" in str(url):
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {
                "access_token": new_access,
                "refresh_token": "rt-new",
                "expires_in": 21600,
                "token_type": "Bearer",
            }
            return r
        r = MagicMock()
        r.status_code = 200
        r.content = bytes([0, 0, 0, 0, 0])
        return r

    client.post.side_effect = post

    key, email, exp, team, note = grok_mod._ensure_fresh_token(home, client, 5.0)
    assert note == "oidc_refreshed"
    assert key == new_access
    assert email == "t@example.com"
    assert team == "team-1"
    assert exp is not None and exp > time.time()

    saved = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    entry = next(iter(saved.values()))
    assert entry["refresh_token"] == "rt-new"
    assert entry["key"] == new_access
    # lock must not be left behind
    assert not (home / "auth.json.lock").exists()


def test_no_refresh_when_token_fresh(tmp_path: Path) -> None:
    home = tmp_path / ".grok"
    # Outside REFRESH_SKEW_S (1h) — must not hit the IdP.
    _write_auth(home, exp=time.time() + 7200)
    client = MagicMock(spec=httpx.Client)
    key, _, exp, _, note = grok_mod._ensure_fresh_token(home, client, 5.0)
    assert note is None
    assert key
    assert exp is not None and exp > time.time()
    client.post.assert_not_called()


def test_refresh_failure_keeps_valid_access(tmp_path: Path) -> None:
    home = tmp_path / ".grok"
    # Within skew window but still not fully expired — refresh fails, keep access.
    _write_auth(home, exp=time.time() + 30)
    client = MagicMock(spec=httpx.Client)
    r = MagicMock()
    r.status_code = 400
    r.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Refresh token has been revoked",
    }
    r.text = "bad"
    client.post.return_value = r

    key, _, exp, _, note = grok_mod._ensure_fresh_token(home, client, 5.0)
    assert key
    assert exp is not None and exp > time.time()
    assert note and "revoked" in note


def test_invalid_grant_accepts_peer_written_token(tmp_path: Path) -> None:
    """CLI already rotated RT; our POST with old RT fails; re-read sees new JWT."""
    home = tmp_path / ".grok"
    old_exp = time.time() - 5
    _write_auth(home, exp=old_exp, refresh="rt-old")
    peer_access = _fake_jwt(time.time() + 7200)

    client = MagicMock(spec=httpx.Client)

    def post(url, **kwargs):
        # Simulate peer (CLI) writing fresh tokens while our request is in flight.
        _write_auth(home, exp=time.time() + 7200, refresh="rt-peer")
        # overwrite key with known peer_access
        data = json.loads((home / "auth.json").read_text(encoding="utf-8"))
        entry = next(iter(data.values()))
        entry["key"] = peer_access
        entry["refresh_token"] = "rt-peer"
        (home / "auth.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        r = MagicMock()
        r.status_code = 400
        r.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Refresh token has been revoked",
        }
        r.text = "revoked"
        return r

    client.post.side_effect = post
    ok, detail = grok_mod._refresh_oidc(home, client, 5.0)
    assert ok is True
    assert detail == "peer_refreshed"
    key, _, exp, _, rt = grok_mod._read_auth(home)
    assert key == peer_access
    assert rt == "rt-peer"
    assert exp is not None and exp > time.time()


def test_already_fresh_under_lock_skips_http(tmp_path: Path) -> None:
    home = tmp_path / ".grok"
    # Under lock JWT is already outside skew — no HTTP.
    _write_auth(home, exp=time.time() + 7200)
    client = MagicMock(spec=httpx.Client)
    ok, detail = grok_mod._refresh_oidc(home, client, 5.0)
    assert ok is True
    assert detail == "already_fresh"
    client.post.assert_not_called()


def test_stale_usage_cache_on_auth_failure(tmp_path: Path) -> None:
    home = tmp_path / ".grok"
    home.mkdir(parents=True, exist_ok=True)
    # No usable auth
    end = time.time() + 3 * 86400
    grok_mod._save_usage_cache(
        home,
        used_pct=40.0,
        rem_pct=60.0,
        period_label="7d",
        period_start=end - 7 * 86400,
        period_end=end,
        email="t@example.com",
    )
    client = MagicMock(spec=httpx.Client)
    r = grok_mod.fetch_grok("grok-personal", "GROK/personal", home, client, 5.0)
    assert r.status == Status.STALE
    assert r.windows
    assert abs(r.windows[0].rem_pct - 60.0) < 1e-6
    assert "last known" in (r.reason or "").lower()
    assert "login" not in (r.reason or "").lower()
    assert r.meta.get("source", "").startswith("local")


def test_revoked_rt_marked_and_not_rehit(tmp_path: Path) -> None:
    home = tmp_path / ".grok"
    _write_auth(home, exp=time.time() + 30, refresh="rt-dead")
    client = MagicMock(spec=httpx.Client)
    bad = MagicMock()
    bad.status_code = 400
    bad.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Refresh token has been revoked",
    }
    bad.text = "revoked"
    client.post.return_value = bad

    key1, _, _, _, note1 = grok_mod._ensure_fresh_token(home, client, 5.0)
    assert key1
    assert note1 and "revoked" in note1
    assert (home / grok_mod.RT_DEAD_NAME).is_file()
    assert client.post.call_count == 1

    # Second ensure within skew must NOT call IdP again.
    key2, _, _, _, note2 = grok_mod._ensure_fresh_token(home, client, 5.0)
    assert key2
    assert note2 == "rt_dead_cached"
    assert client.post.call_count == 1


def test_stale_after_dead_jwt_no_login_nag(tmp_path: Path) -> None:
    home = tmp_path / ".grok"
    _write_auth(home, exp=time.time() - 10, refresh="rt-dead")
    end = time.time() + 3 * 86400
    grok_mod._save_usage_cache(
        home,
        used_pct=25.0,
        rem_pct=75.0,
        period_label="7d",
        period_start=end - 7 * 86400,
        period_end=end,
        email="t@example.com",
    )
    grok_mod._mark_rt_dead(home, "rt-dead", "revoked")
    client = MagicMock(spec=httpx.Client)
    r = grok_mod.fetch_grok("grok-personal", "GROK/personal", home, client, 5.0)
    assert r.status == Status.STALE
    assert r.windows and abs(r.windows[0].rem_pct - 75.0) < 1e-6
    assert "login" not in (r.reason or "").lower()
    client.post.assert_not_called()


def test_auth_lock_format_matches_cli(tmp_path: Path) -> None:
    home = tmp_path / ".grok"
    home.mkdir(parents=True, exist_ok=True)
    seen: list[str] = []

    def grab_while_held():
        lp = home / "auth.json.lock"
        if lp.is_file():
            seen.append(lp.read_text(encoding="utf-8").strip())

    # Hold lock and inspect format
    with grok_mod._auth_lock(home) as held:
        assert held
        grab_while_held()
    assert seen
    pid_s, ts_s = seen[0].split(":")
    assert int(pid_s) == os.getpid()
    assert abs(float(ts_s) - time.time()) < 5
    assert not (home / "auth.json.lock").exists()
