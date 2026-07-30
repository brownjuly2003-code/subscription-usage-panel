"""Gemini Code Assist / Gemini CLI usage (OAuth or API key)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from panel.models import ProfileResult, Status, Window
from panel.timefmt import format_reset_at_iso, format_reset_iso


def _oauth_paths(home: Path) -> list[Path]:
    return [
        home / "oauth_creds.json",
        home / "google_accounts.json",
        home / "credentials.json",
        home / "auth.json",
        Path.home() / ".config" / "gemini" / "oauth_creds.json",
        Path.home() / ".gemini" / "oauth_creds.json",
    ]


def _token(home: Path) -> tuple[str, str]:
    """Return (token, mode) mode=oauth|api."""
    for env in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        if os.environ.get(env):
            return os.environ[env].strip(), "api"
    for p in _oauth_paths(home):
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(d, dict):
            # common shapes
            tok = (
                d.get("access_token")
                or d.get("token")
                or (d.get("tokens") or {}).get("access_token")
            )
            if tok:
                return str(tok).strip(), "oauth"
            # map of accounts
            for v in d.values():
                if isinstance(v, dict):
                    tok = v.get("access_token") or v.get("token")
                    if tok:
                        return str(tok).strip(), "oauth"
    return "", ""


def fetch_gemini(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult:
    t0 = time.perf_counter()
    r = ProfileResult(id=profile_id, family="gemini", label=label, status=Status.DEAD)
    tok, mode = _token(home)
    if not tok:
        r.reason = "no Gemini OAuth/API key (login gemini CLI or set GEMINI_API_KEY)"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    # Code Assist loadCodeAssist / user tier — best-effort undocumented
    if mode == "oauth":
        urls = [
            "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
            "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
        ]
        headers = {
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = json.dumps({"cloudaicompanionProject": None}).encode()
        last_err = "oauth probe failed"
        for url in urls:
            try:
                resp = client.post(url, headers=headers, content=body, timeout=timeout)
            except Exception as e:
                last_err = type(e).__name__
                continue
            if resp.status_code in (401, 403):
                r.status = Status.AUTH
                r.reason = "Gemini OAuth expired — gemini login"
                r.latency_ms = (time.perf_counter() - t0) * 1000
                return r
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                continue
            try:
                data = resp.json()
            except Exception:
                last_err = "bad JSON"
                continue
            # Try extract quota-ish fields if present
            wins = _extract_gemini_windows(data)
            if wins:
                r.status = Status.LIVE
                r.plan = str(
                    data.get("currentTier")
                    or data.get("tierId")
                    or data.get("paidTier")
                    or "gemini"
                )[:32]
                r.windows = wins
                r.meta["source"] = url
                r.latency_ms = (time.perf_counter() - t0) * 1000
                return r
            # auth works but no numeric windows
            r.status = Status.LIVE
            r.plan = "gemini"
            r.windows = [
                Window(
                    label="auth",
                    used_pct=0.0,
                    rem_pct=100.0,
                    reset="",
                    reset_at="",
                )
            ]
            r.meta["note"] = "authenticated; numeric quota not in response"
            r.meta["source"] = url
            r.latency_ms = (time.perf_counter() - t0) * 1000
            return r
        r.status = Status.ERROR
        r.reason = last_err
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    # API key: no public remaining quota — report live key-present with note
    r.status = Status.LIVE
    r.plan = "api-key"
    r.windows = [
        Window(label="key", used_pct=0.0, rem_pct=100.0, reset="", reset_at="")
    ]
    r.meta["note"] = "API key present; Google does not expose remaining % for API keys here"
    r.meta["source"] = "GEMINI_API_KEY"
    r.latency_ms = (time.perf_counter() - t0) * 1000
    return r


def _extract_gemini_windows(data: dict) -> list[Window]:
    out: list[Window] = []
    # recursive search for used/limit percent fields
    def walk(obj, path=""):
        if isinstance(obj, dict):
            keys = {k.lower(): k for k in obj}
            used_k = keys.get("used") or keys.get("usedpercent") or keys.get("utilization")
            lim_k = keys.get("limit") or keys.get("quota") or keys.get("max")
            rem_k = keys.get("remaining") or keys.get("remainingpercent")
            reset_k = keys.get("resets_at") or keys.get("resettime") or keys.get("reset")
            if used_k and lim_k:
                try:
                    u = float(obj[used_k])
                    lim = float(obj[lim_k])
                    if lim > 0 and u <= lim * 5:  # sanity
                        if u <= 100 and lim == 100:
                            pct = u
                        else:
                            pct = u * 100.0 / lim
                        out.append(
                            Window(
                                label="win",
                                used_pct=pct,
                                rem_pct=100.0 - pct,
                                reset=format_reset_iso(str(obj[reset_k])) if reset_k else "",
                                reset_at=format_reset_at_iso(str(obj[reset_k]))
                                if reset_k
                                else "",
                            )
                        )
                except (TypeError, ValueError):
                    pass
            if rem_k and lim_k:
                try:
                    rem = float(obj[rem_k])
                    lim = float(obj[lim_k])
                    if lim > 0:
                        pct_used = (lim - rem) * 100.0 / lim
                        out.append(
                            Window(
                                label="win",
                                used_pct=pct_used,
                                rem_pct=rem * 100.0 / lim if rem <= lim else rem,
                            )
                        )
                except (TypeError, ValueError):
                    pass
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj[:50]:
                walk(v)

    walk(data)
    # keep first 3 unique
    seen = set()
    uniq = []
    for w in out:
        key = (round(w.used_pct, 2), w.label)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(w)
        if len(uniq) >= 3:
            break
    return uniq
