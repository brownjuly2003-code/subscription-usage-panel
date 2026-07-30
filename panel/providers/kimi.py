"""Kimi (Moonshot) coding subscription usage windows."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from panel.models import ProfileResult, Status, Window
from panel.timefmt import format_reset_at_iso, format_reset_iso, parse_pct


def _token(home: Path) -> str:
    for env in (
        "KIMI_API_KEY",
        "MOONSHOT_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
    ):
        if os.environ.get(env):
            return os.environ[env].strip()
    candidates = [
        home / "credentials" / "kimi-code.json",
        home / "kimi-code.json",
        home / "credentials.json",
        home / "auth.json",
        Path.home() / ".kimi-code" / "credentials" / "kimi-code.json",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        tok = d.get("access_token") or d.get("token") or d.get("api_key") or d.get("key")
        if tok:
            exp = d.get("expires_at") or 0
            try:
                exp_i = int(exp)
                if exp_i > 1e12:
                    exp_i //= 1000
                if exp_i > 0 and time.time() >= exp_i:
                    continue
            except (TypeError, ValueError):
                pass
            return str(tok).strip()
    return ""


def fetch_kimi(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult:
    t0 = time.perf_counter()
    r = ProfileResult(id=profile_id, family="kimi", label=label, status=Status.DEAD)
    tok = _token(home)
    if not tok:
        r.reason = "no Kimi token (env or credentials file)"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    base = os.environ.get("KIMI_BASE_URL", "https://api.kimi.com/coding/v1").rstrip("/")
    try:
        resp = client.get(
            f"{base}/usages",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
            timeout=timeout,
        )
    except Exception as e:
        r.status = Status.ERROR
        r.reason = f"network: {type(e).__name__}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code in (401, 403):
        r.status = Status.AUTH
        r.reason = "Kimi token expired — re-login"
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
        r.reason = "bad JSON"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    wins: list[Window] = []
    # 5h-like window: 300 minutes in limits[]
    limits = data.get("limits") or []
    if isinstance(limits, list):
        for item in limits:
            win = (item or {}).get("window") or {}
            detail = (item or {}).get("detail") or item or {}
            dur = win.get("duration")
            unit = str(win.get("timeUnit") or "")
            lim = detail.get("limit")
            used = detail.get("used")
            if lim is None or used is None:
                continue
            try:
                lim_f = float(lim)
                used_f = float(used)
                if lim_f <= 0:
                    continue
                pct = used_f * 100.0 / lim_f
            except (TypeError, ValueError):
                continue
            label_w = "5h" if dur == 300 or "MINUTE" in unit.upper() else "win"
            reset = format_reset_iso(detail.get("resetTime"))
            reset_at = format_reset_at_iso(detail.get("resetTime"))
            wins.append(
                Window(
                    label=label_w,
                    used_pct=pct,
                    rem_pct=100.0 - pct,
                    reset=reset,
                    reset_at=reset_at,
                )
            )

    usage = data.get("usage") or {}
    if usage.get("limit") not in (None, "", 0, "0"):
        try:
            lim_f = float(usage["limit"])
            used_f = float(usage.get("used") or 0)
            if lim_f > 0:
                pct = used_f * 100.0 / lim_f
                wins.append(
                    Window(
                        label="7d",
                        used_pct=pct,
                        rem_pct=100.0 - pct,
                        reset=format_reset_iso(usage.get("resetTime")),
                        reset_at=format_reset_at_iso(usage.get("resetTime")),
                    )
                )
        except (TypeError, ValueError):
            pass

    tq = data.get("totalQuota") or {}
    if tq.get("limit") not in (None, "", 0, "0"):
        try:
            lim_f = float(tq["limit"])
            rem_f = float(tq.get("remaining") or 0)
            if lim_f > 0:
                used_f = lim_f - rem_f
                pct = used_f * 100.0 / lim_f
                wins.append(
                    Window(
                        label="mo",
                        used_pct=pct,
                        rem_pct=100.0 - pct,
                        reset="",
                        reset_at="",
                    )
                )
        except (TypeError, ValueError):
            pass

    if not wins:
        r.status = Status.ERROR
        r.reason = "no usage windows in Kimi response"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    # de-dupe labels keep first
    seen = set()
    uniq = []
    for w in wins:
        if w.label in seen:
            continue
        seen.add(w.label)
        uniq.append(w)

    r.status = Status.LIVE
    r.plan = "kimi"
    r.windows = uniq
    r.meta["source"] = f"{base}/usages"
    r.latency_ms = (time.perf_counter() - t0) * 1000
    return r
