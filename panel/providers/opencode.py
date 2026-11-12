"""OpenCode Zen prepaid balance (pay-as-you-go credits).

The Zen inference API does not report spend, but the OpenCode console API
accepts the same Zen API key as a bearer token:

- ``GET /console/api/billing/status`` -> ``balanceMicroCents``
- ``GET /console/api/usage/summary?range=30d`` -> ``totalCostMicroCents``

Amounts are micro-cents (strings): USD = value / 1e8.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from panel.models import Balance, ProfileResult, Status

CONSOLE_API = "https://opencode.ai/console/api"
MICRO_CENTS_PER_USD = 100_000_000
# Cloudflare answers 403 "error code: 1010" to default library user agents.
USER_AGENT = "subscription-usage-panel/1.2"


def _read_key_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _key(home: Path, key_file: Optional[Path]) -> tuple[str, str]:
    """Return (key, source). Explicit key_file > env > CLI auth.json."""
    if key_file is not None:
        k = _read_key_file(key_file)
        return (k, "key_file") if k else ("", "")
    env = (os.environ.get("OPENCODE_API_KEY") or "").strip()
    if env:
        return env, "env"
    p = home / "auth.json"
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            entry = d.get("opencode") if isinstance(d, dict) else None
            if isinstance(entry, dict):
                k = str(entry.get("key") or "").strip()
                if k:
                    return k, "auth.json"
        except Exception:
            pass
    return "", ""


def _usd(micro_cents: Any) -> Optional[float]:
    if micro_cents is None or isinstance(micro_cents, bool):
        return None
    try:
        return int(str(micro_cents).strip()) / MICRO_CENTS_PER_USD
    except (TypeError, ValueError):
        return None


def _headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def _auth_reason(resp: httpx.Response) -> str:
    code = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            code = str(body.get("code") or "")
    except Exception:
        pass
    if code == "api_key_expired":
        return "ключ OpenCode истёк: создайте новый в OpenCode Console"
    return f"ключ OpenCode отклонён (HTTP {resp.status_code})"


def _spent_30d(client: httpx.Client, key: str, timeout: float) -> Optional[float]:
    try:
        resp = client.get(
            f"{CONSOLE_API}/usage/summary",
            params={"range": "30d"},
            headers=_headers(key),
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    return _usd(body.get("totalCostMicroCents"))


def fetch_opencode(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
    key_file: Optional[Path] = None,
) -> ProfileResult:
    t0 = time.perf_counter()
    r = ProfileResult(id=profile_id, family="opencode", label=label, status=Status.DEAD)
    r.plan = "Zen"

    def done() -> ProfileResult:
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    key, source = _key(home, key_file)
    if not key:
        r.reason = (
            f"нет ключа в {key_file}"
            if key_file is not None
            else "нет ключа OpenCode Zen (key_file / OPENCODE_API_KEY / auth.json)"
        )
        return done()
    r.meta["key_source"] = source

    try:
        resp = client.get(
            f"{CONSOLE_API}/billing/status", headers=_headers(key), timeout=timeout
        )
    except Exception as e:
        r.status = Status.ERROR
        r.reason = f"сеть: {type(e).__name__}"
        return done()

    if resp.status_code in (401, 403):
        r.status = Status.AUTH
        r.reason = _auth_reason(resp)
        return done()
    if resp.status_code != 200:
        r.status = Status.ERROR
        r.reason = f"HTTP {resp.status_code}"
        return done()

    try:
        data = resp.json()
    except Exception:
        data = None
    if not isinstance(data, dict):
        r.status = Status.ERROR
        r.reason = "битый JSON"
        return done()

    amount = _usd(data.get("balanceMicroCents"))
    if amount is None:
        r.status = Status.ERROR
        r.reason = "нет баланса в ответе"
        return done()

    mode = str(data.get("mode") or "")
    if mode == "pay-as-you-go":
        r.plan = "Zen pay-as-you-go"
    elif mode:
        r.plan = f"Zen {mode}"

    r.status = Status.LIVE
    r.balance = Balance(
        amount=amount, currency="USD", spent_30d=_spent_30d(client, key, timeout)
    )
    r.meta["source"] = "opencode console billing/status"
    return done()
