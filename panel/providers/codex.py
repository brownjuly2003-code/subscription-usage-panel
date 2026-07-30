"""Codex subscription usage: ChatGPT plan rate windows (wham/usage)."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Tuple

import httpx

from panel.models import ProfileResult, Status, Window
from panel.timefmt import (
    format_reset_at_epoch,
    format_reset_epoch,
    parse_pct,
    window_label_seconds,
)


def _jwt(id_token: str) -> dict[str, Any]:
    if not id_token or id_token.count(".") != 2:
        return {}
    try:
        p = id_token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


def _auth(home: Path) -> Tuple[str, str, str, str]:
    p = home / "auth.json"
    if not p.is_file():
        return "", "", "", ""
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return "", "", "", ""
    t = d.get("tokens") or {}
    access = (t.get("access_token") or "").strip()
    acc = (t.get("account_id") or "").strip()
    claims = _jwt(t.get("id_token") or "")
    email = str(claims.get("email") or "")
    authc = claims.get("https://api.openai.com/auth") or {}
    plan = str(authc.get("chatgpt_plan_type") or "")
    return access, acc, email, plan


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

    access, acc, email, plan = _auth(home)
    r.email = email
    r.plan = plan

    if not access:
        r.status = Status.DEAD
        r.reason = "нет токена"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    headers = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
    if acc:
        headers["ChatGPT-Account-Id"] = acc

    try:
        resp = client.get(
            "https://chatgpt.com/backend-api/wham/usage",
            headers=headers,
            timeout=timeout,
        )
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
