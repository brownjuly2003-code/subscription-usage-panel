"""Silent OAuth refresh for Codex + Claude providers."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx

from panel.providers import claude as claude_mod
from panel.providers import codex as codex_mod


def _jwt(exp: float) -> str:
    def b64(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64({'exp': exp, 'email': 't@ex.com'})}.sig"


def test_codex_refresh_when_jwt_expired(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    home.mkdir()
    auth = {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": _jwt(time.time() - 10),
            "id_token": _jwt(time.time() + 3600),
            "refresh_token": "rt-old",
            "account_id": "acc-1",
        },
    }
    (home / "auth.json").write_text(json.dumps(auth), encoding="utf-8")

    new_access = _jwt(time.time() + 3600)
    client = MagicMock(spec=httpx.Client)

    def post(url, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {
            "access_token": new_access,
            "refresh_token": "rt-new",
            "id_token": _jwt(time.time() + 3600),
        }
        return r

    client.post.side_effect = post
    access, acc, email, plan, note = codex_mod._ensure_fresh_token(home, client, 5.0)
    assert note == "oauth_refreshed"
    assert access == new_access
    assert acc == "acc-1"
    saved = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    assert saved["tokens"]["refresh_token"] == "rt-new"


def test_codex_skips_refresh_when_fresh(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    home.mkdir()
    auth = {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": _jwt(time.time() + 3600),
            "id_token": _jwt(time.time() + 3600),
            "refresh_token": "rt",
            "account_id": "acc",
        },
    }
    (home / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    client = MagicMock(spec=httpx.Client)
    access, _, _, _, note = codex_mod._ensure_fresh_token(home, client, 5.0)
    assert note is None
    assert access
    client.post.assert_not_called()


def test_claude_refresh_when_expired(tmp_path: Path) -> None:
    home = tmp_path / ".claude"
    home.mkdir()
    data = {
        "claudeAiOauth": {
            "accessToken": "old-tok",
            "refreshToken": "rt-old",
            "expiresAt": int((time.time() - 10) * 1000),
            "subscriptionType": "max",
        }
    }
    (home / ".credentials.json").write_text(json.dumps(data), encoding="utf-8")
    client = MagicMock(spec=httpx.Client)

    def post(url, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {
            "access_token": "new-tok",
            "refresh_token": "rt-new",
            "expires_in": 28800,
        }
        return r

    client.post.side_effect = post
    tok, note = claude_mod._ensure_fresh_token(home, client, 5.0)
    assert note == "oauth_refreshed"
    assert tok == "new-tok"
    saved = json.loads((home / ".credentials.json").read_text(encoding="utf-8"))
    assert saved["claudeAiOauth"]["refreshToken"] == "rt-new"
    assert saved["claudeAiOauth"]["accessToken"] == "new-tok"
