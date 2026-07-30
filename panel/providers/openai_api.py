"""OpenAI API key presence probe (subscription is via Codex/ChatGPT oauth).

When only OPENAI_API_KEY is set, we confirm the key works against /v1/models
and surface remaining as N/A-style live with note — real plan windows stay under family=codex.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from panel.models import ProfileResult, Status, Window


def _key(home: Path) -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"].strip()
    for name in ("key", "api_key", "auth.json", ".openai_api_key"):
        p = home / name
        if not p.is_file():
            continue
        try:
            t = p.read_text(encoding="utf-8").strip()
            if name.endswith(".json"):
                d = json.loads(t)
                k = d.get("OPENAI_API_KEY") or d.get("api_key") or d.get("key")
                if k:
                    return str(k).strip()
            elif t:
                return t
        except Exception:
            pass
    return ""


def fetch_openai_api(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult:
    t0 = time.perf_counter()
    r = ProfileResult(id=profile_id, family="openai", label=label, status=Status.DEAD)
    key = _key(home)
    if not key:
        r.reason = "no OPENAI_API_KEY"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    try:
        resp = client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
    except Exception as e:
        r.status = Status.ERROR
        r.reason = f"network: {type(e).__name__}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code in (401, 403):
        r.status = Status.AUTH
        r.reason = "OpenAI API key rejected"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r
    if resp.status_code != 200:
        r.status = Status.ERROR
        r.reason = f"HTTP {resp.status_code}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    r.status = Status.LIVE
    r.plan = "api-key"
    r.windows = [
        Window(label="key", used_pct=0.0, rem_pct=100.0, reset="", reset_at="")
    ]
    r.meta["note"] = (
        "API key valid. ChatGPT/Codex plan limits are under family=codex profiles."
    )
    r.meta["source"] = "api.openai.com/v1/models"
    r.latency_ms = (time.perf_counter() - t0) * 1000
    return r
