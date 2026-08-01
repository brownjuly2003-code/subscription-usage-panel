"""Claude subscription usage: 5h + 7d utilization (OAuth).

Access tokens expire (~8h); Claude Code silent-refreshes via refreshToken.
The panel must do the same so idle homes do not look dead until next `claude`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional, Tuple

import httpx

from panel.models import ProfileResult, Status, Window
from panel.timefmt import format_reset_at_iso, format_reset_iso, parse_pct


# Claude Code public OAuth client + token endpoint.
OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
REFRESH_SKEW_S = 120.0


def _creds_path(home: Path) -> Path:
    return home / ".credentials.json"


def _load_oauth(home: Path) -> dict[str, Any]:
    p = _creds_path(home)
    if not p.is_file():
        return {}
    try:
        o = json.loads(p.read_text(encoding="utf-8")).get("claudeAiOauth") or {}
        return o if isinstance(o, dict) else {}
    except Exception:
        return {}


def _load_all(home: Path) -> dict[str, Any]:
    p = _creds_path(home)
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_all(home: Path, data: dict[str, Any]) -> None:
    p = _creds_path(home)
    tmp = p.with_suffix(p.suffix + ".panel-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _token(home: Path) -> str:
    return (_load_oauth(home).get("accessToken") or "").strip()


def _refresh_token(home: Path) -> str:
    return (_load_oauth(home).get("refreshToken") or "").strip()


def _expires_at_s(home: Path) -> Optional[float]:
    o = _load_oauth(home)
    exp = o.get("expiresAt") or 0
    try:
        exp_i = float(exp)
    except (TypeError, ValueError):
        return None
    if exp_i <= 0:
        return None
    if exp_i > 1e12:
        exp_i /= 1000.0
    return exp_i


def _plan(home: Path) -> str:
    try:
        o = _load_oauth(home)
        sub = str(o.get("subscriptionType") or "")
        tier = str(o.get("rateLimitTier") or "")
        if "5x" in tier:
            return f"{sub} 5x" if sub else "max 5x"
        if "20x" in tier:
            return f"{sub} 20x" if sub else "max 20x"
        return sub
    except Exception:
        return ""


def _refresh_oauth(
    home: Path, client: httpx.Client, timeout: float
) -> Tuple[bool, str]:
    refresh = _refresh_token(home)
    if not refresh:
        return False, "no refreshToken"
    try:
        resp = client.post(
            OAUTH_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": OAUTH_CLIENT_ID,
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

    data = _load_all(home)
    o = data.get("claudeAiOauth") or {}
    if not isinstance(o, dict):
        o = {}
    o["accessToken"] = access
    if body.get("refresh_token"):
        o["refreshToken"] = body["refresh_token"]
    expires_in = body.get("expires_in")
    if expires_in is not None:
        try:
            o["expiresAt"] = int((time.time() + int(expires_in)) * 1000)
        except (TypeError, ValueError):
            pass
    data["claudeAiOauth"] = o
    try:
        _write_all(home, data)
    except Exception as e:
        return False, f"refresh write failed: {type(e).__name__}"
    return True, "ok"


def _ensure_fresh_token(
    home: Path, client: httpx.Client, timeout: float
) -> Tuple[str, Optional[str]]:
    """Return (access_token, refresh_note)."""
    tok = _token(home)
    refresh = _refresh_token(home)
    exp = _expires_at_s(home)
    now = time.time()
    need = False
    if not tok:
        need = bool(refresh)
    elif exp is not None and exp <= now + REFRESH_SKEW_S:
        need = bool(refresh)
    note: Optional[str] = None
    if need:
        ok, detail = _refresh_oauth(home, client, timeout)
        if ok:
            tok = _token(home)
            note = "oauth_refreshed"
        else:
            note = detail
            if tok and (exp is None or exp > now):
                pass
            elif not tok:
                return "", note
    return tok, note


def _cache(home: Path) -> dict[str, Any] | None:
    for name in (".usage-cache.json",):
        p = home / name
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None


def _windows(data: dict[str, Any]) -> list[Window]:
    out: list[Window] = []
    for label, key in (("5h", "five_hour"), ("7d", "seven_day")):
        b = data.get(key) or {}
        u = parse_pct(b.get("utilization"))
        if u is None:
            continue
        out.append(
            Window(
                label=label,
                used_pct=u,
                rem_pct=100.0 - u,
                reset=format_reset_iso(b.get("resets_at")),
                reset_at=format_reset_at_iso(b.get("resets_at")),
            )
        )
    return out


def _resets_all_expired(data: dict[str, Any]) -> bool:
    """True if every known resets_at is in the past (cache is historically dead)."""
    from datetime import datetime, timezone

    any_ts = False
    now = datetime.now(timezone.utc)
    for key in ("five_hour", "seven_day"):
        ts = (data.get(key) or {}).get("resets_at")
        if not ts:
            continue
        any_ts = True
        try:
            s = str(ts).replace("Z", "+00:00")
            if "." in s:
                head, rest = s.split(".", 1)
                dig = "".join(c for c in rest if c.isdigit())[:6]
                tz = ""
                for i, ch in enumerate(rest):
                    if not ch.isdigit():
                        tz = rest[i:]
                        break
                s = f"{head}.{dig}{tz or '+00:00'}"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt > now:
                return False
        except Exception:
            return False
    return any_ts


def fetch_claude(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult:
    t0 = time.perf_counter()
    r = ProfileResult(id=profile_id, family="claude", label=label, status=Status.DEAD)
    r.plan = _plan(home)

    if not home.is_dir():
        r.reason = "нет home"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    def _maybe_stale(reason: str) -> None:
        """Attach cache windows only if reset times are still in the future."""
        c = _cache(home)
        if not c or not _windows(c):
            return
        if _resets_all_expired(c):
            r.meta["cache_expired"] = True
            r.meta["cache_reason"] = reason
            # do NOT paint fake remaining from dead windows
            return
        r.status = Status.STALE
        r.windows = _windows(c)
        r.reason = reason
        r.meta["source"] = "local .usage-cache.json (not live API)"

    tok, refresh_note = _ensure_fresh_token(home, client, timeout)
    if refresh_note:
        r.meta["auth_refresh"] = refresh_note
    if not tok:
        r.status = Status.DEAD
        r.reason = "нет OAuth-токена"
        if refresh_note and refresh_note not in ("ok", "oauth_refreshed"):
            r.reason = f"нет OAuth-токена ({refresh_note})"
        _maybe_stale("кэш (нет токена)")
        if r.status != Status.STALE and not (
            refresh_note and refresh_note not in ("ok", "oauth_refreshed")
        ):
            r.reason = "нет OAuth-токена (live нет; кэш протух)"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    def _usage(bearer: str) -> httpx.Response:
        return client.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {bearer}",
                "anthropic-beta": "oauth-2025-04-20",
                "Accept": "application/json",
                "User-Agent": "claude-code/2.1.4",
            },
            timeout=timeout,
        )

    try:
        resp = _usage(tok)
    except Exception as e:
        r.status = Status.ERROR
        r.reason = f"сеть: {type(e).__name__}"
        _maybe_stale("сеть · кэш")
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code in (401, 403):
        # 401 = bad/expired token → refresh; 403 may be org policy — still try once.
        ok, detail = _refresh_oauth(home, client, timeout)
        r.meta["auth_refresh"] = "oauth_refreshed" if ok else detail
        if ok:
            tok = _token(home)
            try:
                resp = _usage(tok)
            except Exception as e:
                r.status = Status.ERROR
                r.reason = f"сеть: {type(e).__name__}"
                _maybe_stale("сеть · кэш")
                r.latency_ms = (time.perf_counter() - t0) * 1000
                return r

    if resp.status_code in (401, 403):
        r.status = Status.AUTH
        # Surface org-policy vs plain auth when possible.
        try:
            err = resp.json().get("error") or {}
            msg = str(err.get("message") or "")
            if "organization" in msg.lower() or "oauth" in msg.lower():
                r.reason = msg[:120] or "перелогинься (claude login)"
            else:
                r.reason = "перелогинься (claude login)"
        except Exception:
            r.reason = "перелогинься (claude login)"
        _maybe_stale("401 · кэш")
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code != 200:
        r.status = Status.ERROR
        r.reason = f"HTTP {resp.status_code}"
        _maybe_stale(f"HTTP {resp.status_code} · кэш")
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    try:
        data = resp.json()
    except Exception:
        r.status = Status.ERROR
        r.reason = "битый JSON"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    wins = _windows(data)
    if not wins:
        r.status = Status.ERROR
        r.reason = "нет 5h/7d в ответе"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    r.status = Status.LIVE
    r.windows = wins
    r.meta["source"] = "subscription oauth/usage"
    r.latency_ms = (time.perf_counter() - t0) * 1000
    return r
