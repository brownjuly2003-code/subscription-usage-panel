"""GitHub REST rate-limit remaining (proxy signal when GH_TOKEN set).

Not Copilot premium quota (undocumented), but useful for API-heavy workflows.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

from panel.models import ProfileResult, Status, Window
from panel.timefmt import format_reset_at_epoch, format_reset_epoch


def _token(home: Path) -> str:
    for env in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT"):
        if os.environ.get(env):
            return os.environ[env].strip()
    # gh hosts.yml
    hosts = Path.home() / ".config" / "gh" / "hosts.yml"
    if hosts.is_file():
        try:
            text = hosts.read_text(encoding="utf-8")
            # crude parse oauth_token: xxx
            for line in text.splitlines():
                if "oauth_token:" in line:
                    return line.split(":", 1)[1].strip().strip("\"'")
        except OSError:
            pass
    for name in ("token", "github_token", ".token"):
        p = home / name
        if p.is_file():
            try:
                t = p.read_text(encoding="utf-8").strip()
                if t:
                    return t
            except OSError:
                pass
    return ""


def fetch_github(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult:
    t0 = time.perf_counter()
    r = ProfileResult(id=profile_id, family="github", label=label, status=Status.DEAD)
    tok = _token(home)
    if not tok:
        r.reason = "no GH_TOKEN / GITHUB_TOKEN / gh auth"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    try:
        resp = client.get(
            "https://api.github.com/rate_limit",
            headers={
                "Authorization": f"Bearer {tok}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=timeout,
        )
    except Exception as e:
        r.status = Status.ERROR
        r.reason = f"network: {type(e).__name__}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code in (401, 403):
        # 403 can also be rate limited already
        try:
            data = resp.json()
            if "rate" in (data.get("resources") or data):
                pass
            else:
                r.status = Status.AUTH
                r.reason = "GitHub token rejected"
                r.latency_ms = (time.perf_counter() - t0) * 1000
                return r
        except Exception:
            r.status = Status.AUTH
            r.reason = "GitHub token rejected"
            r.latency_ms = (time.perf_counter() - t0) * 1000
            return r

    if resp.status_code not in (200, 403):
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

    resources = data.get("resources") or {}
    core = resources.get("core") or data.get("rate") or {}
    lim = core.get("limit") or 0
    rem = core.get("remaining")
    reset = core.get("reset")
    if not lim or rem is None:
        r.status = Status.ERROR
        r.reason = "no rate fields"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    used = lim - rem
    used_pct = used * 100.0 / lim
    rem_pct = rem * 100.0 / lim
    r.status = Status.LIVE
    r.plan = "REST"
    r.windows = [
        Window(
            label="1h",
            used_pct=used_pct,
            rem_pct=rem_pct,
            reset=format_reset_epoch(reset),
            reset_at=format_reset_at_epoch(reset),
        )
    ]
    # secondary resources
    for name in ("graphql", "search"):
        res = resources.get(name) or {}
        if not res.get("limit"):
            continue
        lim2 = res["limit"]
        rem2 = res.get("remaining", 0)
        used2 = lim2 - rem2
        r.windows.append(
            Window(
                label=name[:4],
                used_pct=used2 * 100.0 / lim2,
                rem_pct=rem2 * 100.0 / lim2,
                reset=format_reset_epoch(res.get("reset")),
                reset_at=format_reset_at_epoch(res.get("reset")),
            )
        )
    r.meta["source"] = "api.github.com/rate_limit"
    r.meta["note"] = "GitHub REST rate limit (not Copilot premium quota)"
    r.latency_ms = (time.perf_counter() - t0) * 1000
    return r
