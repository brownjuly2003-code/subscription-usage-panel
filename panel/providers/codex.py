"""Codex subscription usage: ChatGPT plan rate windows (wham/usage).

Access tokens expire; Codex CLI silent-refreshes via refresh_token against
auth.openai.com. The panel must do the same so idle profiles do not look dead.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Optional, Tuple

import httpx

from panel.models import ProfileResult, Status, Window
from panel.timefmt import (
    format_reset_at_epoch,
    format_reset_epoch,
    parse_pct,
    window_label_seconds,
)


REFRESH_URL = "https://auth.openai.com/oauth/token"
# Public Codex / ChatGPT OAuth client (same as Codex CLI).
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REFRESH_SKEW_S = 120.0


def _jwt(id_token: str) -> dict[str, Any]:
    if not id_token or id_token.count(".") != 2:
        return {}
    try:
        p = id_token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


def _jwt_exp(token: str) -> Optional[float]:
    claims = _jwt(token)
    exp = claims.get("exp")
    try:
        return float(exp) if exp is not None else None
    except (TypeError, ValueError):
        return None


def _auth_path(home: Path) -> Path:
    return home / "auth.json"


def _load_auth(home: Path) -> dict[str, Any]:
    p = _auth_path(home)
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_auth(home: Path, data: dict[str, Any]) -> None:
    p = _auth_path(home)
    tmp = p.with_suffix(p.suffix + ".panel-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _auth(home: Path) -> Tuple[str, str, str, str, str]:
    """access, account_id, email, plan, refresh_token."""
    d = _load_auth(home)
    t = d.get("tokens") or {}
    if not isinstance(t, dict):
        t = {}
    access = (t.get("access_token") or "").strip()
    acc = (t.get("account_id") or "").strip()
    refresh = (t.get("refresh_token") or "").strip()
    claims = _jwt(t.get("id_token") or "")
    email = str(claims.get("email") or "")
    authc = claims.get("https://api.openai.com/auth") or {}
    plan = str(authc.get("chatgpt_plan_type") or "")
    return access, acc, email, plan, refresh


def _refresh_oauth(
    home: Path, client: httpx.Client, timeout: float
) -> Tuple[bool, str]:
    data = _load_auth(home)
    t = data.get("tokens") or {}
    if not isinstance(t, dict):
        return False, "no tokens"
    refresh = (t.get("refresh_token") or "").strip()
    if not refresh:
        return False, "no refresh_token"
    try:
        resp = client.post(
            REFRESH_URL,
            json={
                "client_id": CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
    except Exception as e:
        return False, f"refresh network: {type(e).__name__}"

    if resp.status_code != 200:
        detail = ""
        try:
            err = resp.json()
            detail = str(err.get("error_description") or err.get("error") or "")
        except Exception:
            detail = (resp.text or "")[:120]
        return False, f"refresh HTTP {resp.status_code}" + (
            f": {detail}" if detail else ""
        )

    try:
        body = resp.json()
    except Exception:
        return False, "refresh: bad JSON"
    access = str(body.get("access_token") or "").strip()
    if not access:
        return False, "refresh: no access_token"
    t["access_token"] = access
    if body.get("id_token"):
        t["id_token"] = body["id_token"]
    if body.get("refresh_token"):
        t["refresh_token"] = body["refresh_token"]
    data["tokens"] = t
    data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    try:
        _write_auth(home, data)
    except Exception as e:
        return False, f"refresh write failed: {type(e).__name__}"
    return True, "ok"


def _ensure_fresh_token(
    home: Path, client: httpx.Client, timeout: float
) -> Tuple[str, str, str, str, Optional[str]]:
    """access, account_id, email, plan, optional refresh note."""
    access, acc, email, plan, refresh = _auth(home)
    exp = _jwt_exp(access)
    now = time.time()
    need = False
    if not access:
        need = bool(refresh)
    elif exp is not None and exp <= now + REFRESH_SKEW_S:
        need = bool(refresh)
    note: Optional[str] = None
    if need:
        ok, detail = _refresh_oauth(home, client, timeout)
        if ok:
            access, acc, email, plan, _ = _auth(home)
            note = "oauth_refreshed"
        else:
            note = detail
            if access and (exp is None or exp > now):
                pass
            elif not access:
                return "", acc, email, plan, note
    return access, acc, email, plan, note


def fetch_codex(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult:
    t0 = time.perf_counter()
    r = ProfileResult(id=profile_id, family="codex", label=label, status=Status.DEAD)

    if not home.is_dir():
        r.reason = "нет home"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    access, acc, email, plan, refresh_note = _ensure_fresh_token(home, client, timeout)
    r.email = email
    r.plan = plan
    if refresh_note:
        r.meta["auth_refresh"] = refresh_note

    if not access:
        r.status = Status.DEAD
        r.reason = "нет токена"
        if refresh_note and refresh_note not in ("ok", "oauth_refreshed"):
            r.reason = f"нет токена ({refresh_note})"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    def _get(bearer: str) -> httpx.Response:
        headers = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
        if acc:
            headers["ChatGPT-Account-Id"] = acc
        return client.get(
            "https://chatgpt.com/backend-api/wham/usage",
            headers=headers,
            timeout=timeout,
        )

    try:
        resp = _get(access)
    except Exception as e:
        r.status = Status.ERROR
        r.reason = f"сеть: {type(e).__name__}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code in (401, 403):
        ok, detail = _refresh_oauth(home, client, timeout)
        r.meta["auth_refresh"] = "oauth_refreshed" if ok else detail
        if ok:
            access, acc, email, plan, _ = _auth(home)
            r.email = email or r.email
            r.plan = plan or r.plan
            try:
                resp = _get(access)
            except Exception as e:
                r.status = Status.ERROR
                r.reason = f"сеть: {type(e).__name__}"
                r.latency_ms = (time.perf_counter() - t0) * 1000
                return r

    if resp.status_code in (401, 403):
        r.status = Status.AUTH
        r.reason = "перелогинься (codex login)"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code != 200:
        r.status = Status.ERROR
        r.reason = f"HTTP {resp.status_code}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    try:
        data = resp.json()
    except Exception:
        r.status = Status.ERROR
        r.reason = "битый JSON"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if not r.plan:
        r.plan = str(data.get("plan_type") or "")
    if not r.email:
        r.email = str(data.get("email") or "")

    rl = data.get("rate_limit") or {}
    wins: list[Window] = []
    for key in ("primary_window", "secondary_window"):
        w = rl.get(key)
        if not isinstance(w, dict):
            continue
        u = parse_pct(w.get("used_percent"))
        if u is None:
            continue
        wins.append(
            Window(
                label=window_label_seconds(w.get("limit_window_seconds")),
                used_pct=u,
                rem_pct=100.0 - u,
                reset=format_reset_epoch(w.get("reset_at")),
                reset_at=format_reset_at_epoch(w.get("reset_at")),
            )
        )

    # model-specific subscription limits (still plan usage)
    for item in data.get("additional_rate_limits") or []:
        name = str(item.get("limit_name") or "")[:8]
        sub = (item.get("rate_limit") or {}).get("primary_window") or {}
        u = parse_pct(sub.get("used_percent"))
        if u is None:
            continue
        wins.append(
            Window(
                label=name or "xtra",
                used_pct=u,
                rem_pct=100.0 - u,
                reset=format_reset_epoch(sub.get("reset_at")),
                reset_at=format_reset_at_epoch(sub.get("reset_at")),
            )
        )

    if not wins:
        r.status = Status.ERROR
        r.reason = "нет rate_limit окон"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    r.status = Status.LIVE
    r.windows = wins
    r.meta["source"] = "subscription wham/usage"
    r.latency_ms = (time.perf_counter() - t0) * 1000
    return r
