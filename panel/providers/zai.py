"""z.ai GLM Coding Plan quota (5h + weekly credit windows)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from panel.models import ProfileResult, Status, Window
from panel.timefmt import format_reset_at_epoch, format_reset_epoch

QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit"
PLAN_LABELS = {
    "lite": "Lite",
    "standard": "Pro",
    "pro": "Max",
}


def _key(home: Path) -> str:
    for env in ("ZAI_API_KEY", "Z_AI_API_KEY", "GLM_API_KEY"):
        v = os.environ.get(env)
        if v:
            return v.strip()
    for name in ("api_key", "key", ".env"):
        p = home / name
        if not p.is_file():
            continue
        try:
            t = p.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if name == ".env":
            for line in t.splitlines():
                if line.startswith(("ZAI_API_KEY=", "Z_AI_API_KEY=", "GLM_API_KEY=")):
                    return line.split("=", 1)[1].strip().strip("\"'")
        elif t:
            return t
    for name in ("auth.json", "credentials.json"):
        p = home / name
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        k = d.get("api_key") or d.get("key") or d.get("token") or d.get("access_token")
        if k:
            return str(k).strip()
    return ""


def _window_label(item: dict) -> str:
    typ = str(item.get("type") or "").upper()
    try:
        unit = int(item.get("unit"))
    except (TypeError, ValueError):
        unit = -1
    try:
        number = int(item.get("number"))
    except (TypeError, ValueError):
        number = -1
    if unit == 3 and number == 5:
        return "5h"
    if unit == 6:
        return "7d"
    if typ == "TIME_LIMIT" or (unit == 5 and number == 1):
        return "mo"
    if typ in ("TOKENS_LIMIT", "CREDIT_LIMIT"):
        if number == 5:
            return "5h"
        if number in (1, 7):
            return "7d"
    return "win"


def _windows_from_limits(limits: list) -> list[Window]:
    wins: list[Window] = []
    seen: set[str] = set()
    for item in limits:
        if not isinstance(item, dict):
            continue
        used_pct = None
        rem_pct = None
        pct = item.get("percentage")
        usage = item.get("usage")
        remaining = item.get("remaining")
        current = item.get("currentValue")
        try:
            if pct is not None:
                used_pct = float(pct)
                rem_pct = max(0.0, 100.0 - used_pct)
            elif usage is not None and remaining is not None:
                lim = float(usage)
                rem = float(remaining)
                if lim > 0:
                    rem_pct = rem * 100.0 / lim
                    used_pct = max(0.0, 100.0 - rem_pct)
            elif usage is not None and current is not None:
                lim = float(usage)
                used = float(current)
                if lim > 0:
                    used_pct = used * 100.0 / lim
                    rem_pct = max(0.0, 100.0 - used_pct)
        except (TypeError, ValueError):
            continue
        if used_pct is None or rem_pct is None:
            continue
        label = _window_label(item)
        if label in seen:
            continue
        seen.add(label)
        reset_ts = item.get("nextResetTime")
        wins.append(
            Window(
                label=label,
                used_pct=used_pct,
                rem_pct=rem_pct,
                reset=format_reset_epoch(reset_ts),
                reset_at=format_reset_at_epoch(reset_ts),
            )
        )
    return wins


def fetch_zai(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult:
    t0 = time.perf_counter()
    r = ProfileResult(id=profile_id, family="zai", label=label, status=Status.DEAD)
    key = _key(home)
    if not key:
        r.reason = "no ZAI_API_KEY / home key file"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    try:
        resp = client.get(
            QUOTA_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
    except Exception as e:
        r.status = Status.ERROR
        r.reason = f"network: {type(e).__name__}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code in (401, 403):
        r.status = Status.AUTH
        r.reason = "invalid z.ai key"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r
    if resp.status_code != 200:
        r.status = Status.ERROR
        r.reason = f"HTTP {resp.status_code}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    try:
        payload = resp.json()
    except Exception:
        r.status = Status.ERROR
        r.reason = "bad JSON"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    code = payload.get("code") if isinstance(payload, dict) else None
    if code not in (None, 200, "200"):
        r.status = Status.ERROR
        r.reason = f"z.ai code {code}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    inner = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(inner, dict):
        inner = payload if isinstance(payload, dict) else {}
    limits = inner.get("limits") or []
    if not isinstance(limits, list):
        limits = []
    wins = _windows_from_limits(limits)
    if not wins:
        r.status = Status.ERROR
        r.reason = "no usage windows in z.ai response"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    level = str(inner.get("level") or "").strip().lower()
    r.status = Status.LIVE
    r.plan = PLAN_LABELS.get(level, level or "GLM Coding")
    r.windows = wins
    r.meta["source"] = "api.z.ai /api/monitor/usage/quota/limit"
    if level:
        r.meta["level"] = level
    r.latency_ms = (time.perf_counter() - t0) * 1000
    return r
