"""Claude subscription usage: 5h + 7d utilization (OAuth)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from panel.models import ProfileResult, Status, Window
from panel.timefmt import format_reset_at_iso, format_reset_iso, parse_pct


def _token(home: Path) -> str:
    p = home / ".credentials.json"
    if not p.is_file():
        return ""
    try:
        o = json.loads(p.read_text(encoding="utf-8")).get("claudeAiOauth") or {}
        return (o.get("accessToken") or "").strip()
    except Exception:
        return ""


def _plan(home: Path) -> str:
    p = home / ".credentials.json"
    if not p.is_file():
        return ""
    try:
        o = json.loads(p.read_text(encoding="utf-8")).get("claudeAiOauth") or {}
        sub = str(o.get("subscriptionType") or "")
        tier = str(o.get("rateLimitTier") or "")
        if "5x" in tier:
            return f"{sub} 5x" if sub else "max 5x"
        if "20x" in tier:
            return f"{sub} 20x" if sub else "max 20x"
        return sub
    except Exception:
        return ""


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

    tok = _token(home)
    if not tok:
        r.status = Status.DEAD
        r.reason = "нет OAuth-токена"
        _maybe_stale("кэш (нет токена)")
        if r.status != Status.STALE:
            r.reason = "нет OAuth-токена (live нет; кэш протух)"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    try:
        resp = client.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {tok}",
                "anthropic-beta": "oauth-2025-04-20",
                "Accept": "application/json",
                "User-Agent": "claude-code/2.1.4",
            },
            timeout=timeout,
        )
    except Exception as e:
        r.status = Status.ERROR
        r.reason = f"сеть: {type(e).__name__}"
        _maybe_stale(f"сеть · кэш")
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code in (401, 403):
        r.status = Status.AUTH
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
