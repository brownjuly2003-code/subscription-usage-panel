"""Grok SuperGrok subscription usage via GetGrokCreditsConfig (CodexBar path).

NOT cli-chat-proxy /v1/billing monthly API credits (that was the 109% garbage).
This is the gRPC-web endpoint that returns credit_usage_percent for the plan pool.

OIDC access tokens (~6h) expire independently of SuperGrok; Grok CLI silent-refreshes
via refresh_token. The panel must do the same — otherwise a valid session looks like
"JWT истёк" until the next interactive `grok` run rewrites auth.json.
"""
from __future__ import annotations

import base64
import json
import struct
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

import httpx

from panel.models import ProfileResult, Status, Window
from panel.timefmt import (
    fmt_diff_seconds,
    format_reset_at_epoch,
    format_reset_epoch,
)


GRPC_URL = "https://grok.com/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig"
DEFAULT_OIDC_ISSUER = "https://auth.x.ai"
DEFAULT_OIDC_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
# Refresh a bit before JWT exp so the next poll never hard-fails on clock skew.
REFRESH_SKEW_S = 120.0


def _jwt_exp(token: str) -> Optional[float]:
    if not token or token.count(".") != 2:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        if "exp" in claims:
            return float(claims["exp"])
    except Exception:
        return None
    return None


def _auth_path(home: Path) -> Path:
    return home / "auth.json"


def _load_auth(home: Path) -> Tuple[dict[str, Any], str, dict[str, Any]]:
    """Return (top-level auth.json dict, entry_key, entry) or empty structures."""
    p = _auth_path(home)
    if not p.is_file():
        return {}, "", {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}, "", {}
    if not isinstance(data, dict):
        return {}, "", {}
    for k, v in data.items():
        if isinstance(v, dict) and (v.get("key") or v.get("refresh_token")):
            return data, str(k), v
    return data, "", {}


def _read_auth(home: Path) -> Tuple[str, str, Optional[float], str, str]:
    """key, email, exp, team_id, refresh_token."""
    _, _, entry = _load_auth(home)
    if not entry:
        return "", "", None, "", ""
    key = (entry.get("key") or "").strip()
    email = str(entry.get("email") or "")
    exp = _jwt_exp(key)
    refresh = str(entry.get("refresh_token") or "").strip()
    return key, email, exp, str(entry.get("team_id") or ""), refresh


def _token_endpoint(issuer: str) -> str:
    iss = (issuer or DEFAULT_OIDC_ISSUER).rstrip("/")
    # auth.x.ai and typical OIDC IdPs expose this well-known path; fall back to /oauth2/token.
    return f"{iss}/oauth2/token"


def _write_auth(home: Path, data: dict[str, Any]) -> None:
    """Atomic replace of auth.json (refresh_token rotates — must not lose the new one)."""
    p = _auth_path(home)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp = p.with_suffix(p.suffix + ".panel-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


def _refresh_oidc(
    home: Path, client: httpx.Client, timeout: float
) -> Tuple[bool, str]:
    """Silent OIDC refresh using stored refresh_token. Updates auth.json in place.

    Returns (ok, detail). On success auth.json has a fresh access token (+ rotated refresh).
    """
    data, entry_key, entry = _load_auth(home)
    if not entry or not entry_key:
        return False, "no auth entry"
    refresh = str(entry.get("refresh_token") or "").strip()
    if not refresh:
        return False, "no refresh_token"
    client_id = str(
        entry.get("oidc_client_id") or DEFAULT_OIDC_CLIENT_ID
    ).strip()
    issuer = str(entry.get("oidc_issuer") or DEFAULT_OIDC_ISSUER).strip()
    url = _token_endpoint(issuer)
    try:
        resp = client.post(
            url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": client_id,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
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
        return False, f"refresh HTTP {resp.status_code}" + (f": {detail}" if detail else "")

    try:
        body = resp.json()
    except Exception:
        return False, "refresh: bad JSON"
    access = str(body.get("access_token") or "").strip()
    if not access:
        return False, "refresh: no access_token"
    new_refresh = str(body.get("refresh_token") or "").strip() or refresh
    expires_in = body.get("expires_in")
    now = datetime.now(timezone.utc)
    if expires_in is not None:
        try:
            exp_dt = now + timedelta(seconds=int(expires_in))
            entry["expires_at"] = exp_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{exp_dt.microsecond:06d}Z"
        except Exception:
            entry["expires_at"] = now.isoformat().replace("+00:00", "Z")
    entry["key"] = access
    entry["refresh_token"] = new_refresh
    entry["create_time"] = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"
    data[entry_key] = entry
    try:
        _write_auth(home, data)
    except Exception as e:
        return False, f"refresh write failed: {type(e).__name__}"
    return True, "ok"


def _ensure_fresh_token(
    home: Path, client: httpx.Client, timeout: float
) -> Tuple[str, str, Optional[float], str, Optional[str]]:
    """Return key, email, exp, team; optional refresh note for meta.

    Refreshes when JWT missing/expired or within REFRESH_SKEW_S of expiry.
    """
    key, email, exp, team, refresh = _read_auth(home)
    now = time.time()
    need = False
    if not key:
        need = bool(refresh)
    elif exp is not None and exp <= now + REFRESH_SKEW_S:
        need = bool(refresh)
    note: Optional[str] = None
    if need:
        ok, detail = _refresh_oidc(home, client, timeout)
        if ok:
            key, email, exp, team, _ = _read_auth(home)
            note = "oidc_refreshed"
        else:
            note = detail
            # Keep using non-expired access token if refresh failed (e.g. revoked refresh).
            if key and (exp is None or exp > now):
                pass
            else:
                return key, email, exp, team, note
    return key, email, exp, team, note


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    v = 0
    s = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        v |= (b & 0x7F) << s
        if not (b & 0x80):
            return v, i
        s += 7
    return v, i


def _parse_timestamp_msg(buf: bytes) -> Optional[float]:
    """google.protobuf.Timestamp → epoch seconds."""
    i = 0
    seconds = None
    while i < len(buf):
        tag = buf[i]
        i += 1
        field, wt = tag >> 3, tag & 7
        if wt == 0:
            val, i = _read_varint(buf, i)
            if field == 1:
                seconds = val
        elif wt == 5:
            i += 4
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            i += ln
        elif wt == 1:
            i += 8
        else:
            break
    return float(seconds) if seconds is not None else None


def parse_credits_config(body: bytes) -> dict[str, Any]:
    """Parse gRPC-web response → {used_pct, period_start, period_end}."""
    out: dict[str, Any] = {}
    i = 0
    while i + 5 <= len(body):
        flags = body[i]
        length = int.from_bytes(body[i + 1 : i + 5], "big")
        i += 5
        if i + length > len(body):
            break
        payload = body[i : i + length]
        i += length
        if flags & 0x80:
            continue  # trailer
        # outer message field 1 = GrokCreditsConfig
        j = 0
        while j < len(payload):
            tag = payload[j]
            j += 1
            field, wt = tag >> 3, tag & 7
            if wt != 2:
                if wt == 0:
                    _, j = _read_varint(payload, j)
                elif wt == 5:
                    j += 4
                elif wt == 1:
                    j += 8
                else:
                    break
                continue
            ln, j = _read_varint(payload, j)
            msg = payload[j : j + ln]
            j += ln
            if field != 1:
                continue
            # inner config
            k = 0
            while k < len(msg):
                t2 = msg[k]
                k += 1
                f2, w2 = t2 >> 3, t2 & 7
                if w2 == 5:  # fixed32 float
                    if k + 4 > len(msg):
                        break
                    raw = msg[k : k + 4]
                    k += 4
                    if f2 == 1:
                        out["used_pct"] = struct.unpack("<f", raw)[0]
                elif w2 == 2:
                    ln2, k = _read_varint(msg, k)
                    sub = msg[k : k + ln2]
                    k += ln2
                    if f2 == 4:  # period start
                        ts = _parse_timestamp_msg(sub)
                        if ts:
                            out["period_start"] = ts
                    elif f2 == 5:  # period end
                        ts = _parse_timestamp_msg(sub)
                        if ts:
                            out["period_end"] = ts
                    elif f2 == 7:
                        # nested may also carry float percent
                        m = 0
                        while m < len(sub):
                            t3 = sub[m]
                            m += 1
                            f3, w3 = t3 >> 3, t3 & 7
                            if w3 == 5 and m + 4 <= len(sub):
                                if f3 == 2 or f3 == 1:
                                    val = struct.unpack("<f", sub[m : m + 4])[0]
                                    if "used_pct" not in out:
                                        out["used_pct"] = val
                                m += 4
                            elif w3 == 0:
                                _, m = _read_varint(sub, m)
                            elif w3 == 2:
                                ln3, m = _read_varint(sub, m)
                                m += ln3
                            else:
                                break
                elif w2 == 0:
                    _, k = _read_varint(msg, k)
                elif w2 == 1:
                    k += 8
                else:
                    break
    return out


def _period_label(start: Optional[float], end: Optional[float]) -> str:
    if start is None or end is None:
        return "pool"
    days = (end - start) / 86400.0
    if 5.5 <= days <= 8.5:
        return "7d"
    if 25 <= days <= 35:
        return "mo"
    return "pool"


def fetch_grok(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult:
    t0 = time.perf_counter()
    r = ProfileResult(id=profile_id, family="grok", label=label, status=Status.DEAD)

    if not home.is_dir():
        r.reason = "нет home"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    key, email, exp, team, refresh_note = _ensure_fresh_token(home, client, timeout)
    r.email = email
    if team:
        r.meta["team_id"] = team
    if refresh_note:
        r.meta["auth_refresh"] = refresh_note

    if not key:
        r.status = Status.DEAD
        r.reason = "нет OIDC (grok login)"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    now = time.time()
    if exp is not None and exp <= now:
        # Refresh was attempted (if refresh_token existed) and still expired.
        r.status = Status.AUTH
        r.reason = "JWT истёк — grok login"
        if refresh_note and refresh_note not in ("ok", "oidc_refreshed"):
            r.reason = f"JWT истёк ({refresh_note})"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    # empty protobuf request framed for gRPC-web
    frame = bytes([0, 0, 0, 0, 0])

    def _post(bearer: str) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/grpc-web+proto",
            "Accept": "application/grpc-web+proto",
            "X-Grpc-Web": "1",
            "User-Agent": "grok-cli",
            "Origin": "https://grok.com",
            "Referer": "https://grok.com/",
        }
        return client.post(GRPC_URL, headers=headers, content=frame, timeout=timeout)

    try:
        resp = _post(key)
    except Exception as e:
        r.status = Status.ERROR
        r.reason = f"сеть: {type(e).__name__}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code in (401, 403):
        # Access rejected — try one forced refresh even if JWT exp looked fine.
        ok, detail = _refresh_oidc(home, client, timeout)
        r.meta["auth_refresh"] = "oidc_refreshed" if ok else detail
        if ok:
            key, email, exp, team, _ = _read_auth(home)
            r.email = email or r.email
            if team:
                r.meta["team_id"] = team
            try:
                resp = _post(key)
            except Exception as e:
                r.status = Status.ERROR
                r.reason = f"сеть: {type(e).__name__}"
                r.latency_ms = (time.perf_counter() - t0) * 1000
                return r

    if resp.status_code in (401, 403):
        r.status = Status.AUTH
        r.reason = "auth rejected — grok login / cookies"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    if resp.status_code != 200:
        r.status = Status.ERROR
        r.reason = f"HTTP {resp.status_code}"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    parsed = parse_credits_config(resp.content)
    used = parsed.get("used_pct")
    if used is None:
        r.status = Status.ERROR
        r.reason = "нет credit_usage_percent в gRPC"
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    used_f = float(used)
    # proto3: omitted percent = 0 is valid
    end = parsed.get("period_end")
    start = parsed.get("period_start")
    lbl = _period_label(start, end)
    reset = format_reset_epoch(end) if end else ""
    reset_at = format_reset_at_epoch(end) if end else ""

    r.windows = [
        Window(
            label=lbl,
            used_pct=used_f,
            rem_pct=100.0 - used_f,
            reset=reset,
            reset_at=reset_at,
        )
    ]
    r.plan = "SuperGrok"
    r.status = Status.LIVE
    r.meta["source"] = "subscription GetGrokCreditsConfig"
    r.meta["used_pct"] = used_f
    if start:
        r.meta["period_start"] = datetime.fromtimestamp(
            start, tz=timezone.utc
        ).isoformat()
    if end:
        r.meta["period_end"] = datetime.fromtimestamp(end, tz=timezone.utc).isoformat()
    if exp is not None:
        r.meta["token_left"] = fmt_diff_seconds(exp - now)

    r.latency_ms = (time.perf_counter() - t0) * 1000
    return r
