"""OpenRouter prepaid credits remaining (key balance)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from panel.models import ProfileResult, Status, Window


def _key(home: Path) -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()
    for name in ("key", "api_key", ".env"):
        p = home / name
        if p.is_file():
            try:
                t = p.read_text(encoding="utf-8").strip()
                if name == ".env":
                    for line in t.splitlines():
                        if line.startswith("OPENROUTER_API_KEY="):
                            return line.split("=", 1)[1].strip().strip("\"'")
                elif t:
                    return t
            except OSError:
                pass
    # oauth-style json
    for name in ("auth.json", "credentials.json"):
        p = home / name
        if p.is_file():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                k = d.get("key") or d.get("api_key") or d.get("token")
                if k:
                    return str(k).strip()
            except Exception:
                pass
    return ""


def fetch_openrouter(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult:
    t0 = time.perf_counter()
    r = ProfileResult(
        id=profile_id, family="openrouter", label=label, status=Status.DEAD
    )
    key = _key(home)
    if not key:
        r.reason = "no OPENROUTER_API_KEY / home key file"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    try:
        resp = client.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=timeout,
        )
    except Exception as e:
        r.status = Status.ERROR
        r.reason = f"network: {type(e).__name__}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code in (401, 403):
        r.status = Status.AUTH
        r.reason = "invalid OpenRouter key"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r
    if resp.status_code != 200:
        r.status = Status.ERROR
        r.reason = f"HTTP {resp.status_code}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    try:
        data = resp.json().get("data") or resp.json()
    except Exception:
        r.status = Status.ERROR
        r.reason = "bad JSON"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    # limit_remaining is often null; usage vs limit
    limit = data.get("limit")
    usage = data.get("usage")
    limit_rem = data.get("limit_remaining")
    is_free = data.get("is_free_tier")

    used_pct = None
    rem_pct = None
    if limit is not None and usage is not None:
        try:
            lim = float(limit)
            usg = float(usage)
            if lim > 0:
                used_pct = usg * 100.0 / lim
                rem_pct = max(0.0, 100.0 - used_pct)
        except (TypeError, ValueError):
            pass
    if rem_pct is None and limit_rem is not None and limit is not None:
        try:
            lim = float(limit)
            rem = float(limit_rem)
            if lim > 0:
                rem_pct = rem * 100.0 / lim
                used_pct = 100.0 - rem_pct
        except (TypeError, ValueError):
            pass

    if rem_pct is None:
        # unlimited or no limit set — report live with 100% rem placeholder note
        r.status = Status.LIVE
        r.plan = "free" if is_free else "credits"
        r.reason = ""
        r.windows = [
            Window(
                label="bal",
                used_pct=0.0 if limit is None else (used_pct or 0),
                rem_pct=100.0 if limit is None else (rem_pct or 0),
                reset="",
                reset_at="",
            )
        ]
        if limit is None:
            r.meta["note"] = "no hard limit on key (usage tracked only)"
            r.meta["usage"] = usage
        r.meta["source"] = "openrouter /api/v1/key"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    r.status = Status.LIVE
    r.plan = "free" if is_free else "credits"
    r.windows = [
        Window(
            label="lim",
            used_pct=float(used_pct or 0),
            rem_pct=float(rem_pct),
            reset="",
            reset_at="",
        )
    ]
    r.meta["source"] = "openrouter /api/v1/key"
    r.meta["usage"] = usage
    r.meta["limit"] = limit
    r.latency_ms = (time.perf_counter() - t0) * 1000
    return r
