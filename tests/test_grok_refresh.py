"""Grok OIDC silent refresh (auth.json rotation)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx

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
        # billing
        r = MagicMock()
        r.status_code = 200
        # minimal grpc-web frame with empty message → parse fails → ERROR unless we craft body
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


def test_no_refresh_when_token_fresh(tmp_path: Path) -> None:
    home = tmp_path / ".grok"
    _write_auth(home, exp=time.time() + 3600)
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
