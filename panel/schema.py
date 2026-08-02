"""Versioned JSON schema for agents and dashboards (sup.v1)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from panel.models import ProfileResult, Status

SCHEMA_VERSION = "sup.v1"

# remaining thresholds
WARN_REM = 20.0
CRIT_REM = 10.0


def _window_dict(w) -> dict[str, Any]:
    return {
        "label": w.label,
        "period": _period_name(w.label),
        "used_pct": round(float(w.used_pct), 4),
        "remaining_pct": round(float(w.rem_pct), 4),
        "reset_in": w.reset or None,
        "reset_at": w.reset_at or None,
    }


def _period_name(label: str) -> str:
    return {
        "7d": "week",
        "5h": "5 hours",
        "1d": "day",
        "mo": "month",
        "pool": "period",
    }.get((label or "").lower(), label or "period")


def primary_remaining(r: ProfileResult) -> float | None:
    if not r.windows:
        return None
    return min(float(w.rem_pct) for w in r.windows)


def urgency_level(rem: float | None, status: Status) -> str:
    if status in (Status.DEAD, Status.AUTH, Status.ERROR) and rem is None:
        return "offline"
    if rem is None:
        return "unknown"
    if rem <= CRIT_REM:
        return "critical"
    if rem <= WARN_REM:
        return "warn"
    return "ok"


def build_payload(
    results: list[ProfileResult],
    wall_ms: float,
    *,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profiles = []
    alerts: list[dict[str, Any]] = []

    for r in results:
        rem = primary_remaining(r)
        level = urgency_level(rem, r.status)
        pw = None
        if r.windows:
            pw = min(r.windows, key=lambda w: w.rem_pct)
        entry = {
            "id": r.id,
            "family": r.family,
            "label": r.label,
            "status": r.status.value,
            "reason": r.reason or None,
            "plan": r.plan or None,
            "email": r.email or None,
            "latency_ms": round(r.latency_ms, 1),
            "urgency": level,
            "primary": (
                {
                    "period": _period_name(pw.label),
                    "window_label": pw.label,
                    "used_pct": round(float(pw.used_pct), 4),
                    "remaining_pct": round(float(pw.rem_pct), 4),
                    "reset_in": pw.reset or None,
                    "reset_at": pw.reset_at or None,
                }
                if pw
                else None
            ),
            "windows": [_window_dict(w) for w in r.windows],
            "meta": r.meta or {},
        }
        profiles.append(entry)
        if level in ("critical", "warn") and rem is not None:
            alerts.append(
                {
                    "level": level,
                    "profile_id": r.id,
                    "label": r.label,
                    "remaining_pct": round(rem, 4),
                    "reset_at": pw.reset_at if pw else None,
                    "message": f"{r.label}: {rem:.1f}% remaining",
                }
            )
        elif r.status in (Status.AUTH, Status.DEAD, Status.STALE) and r.family in (
            "claude",
            "codex",
            "grok",
        ):
            # only alert offline if it looks like a main account with a reason
            if r.reason:
                alerts.append(
                    {
                        "level": "offline",
                        "profile_id": r.id,
                        "label": r.label,
                        "remaining_pct": rem,
                        "reset_at": pw.reset_at if pw else None,
                        "message": f"{r.label}: {r.reason}",
                    }
                )
        # Grok/Claude: live probe but refresh_token already dead — warn before blank.
        auth_note = str((r.meta or {}).get("auth_refresh") or "")
        if (
            r.status == Status.LIVE
            and r.family == "grok"
            and auth_note
            and (
                "revoked" in auth_note.lower()
                or "invalid_grant" in auth_note.lower()
            )
        ):
            alerts.append(
                {
                    "level": "warn",
                    "profile_id": r.id,
                    "label": r.label,
                    "remaining_pct": rem,
                    "reset_at": pw.reset_at if pw else None,
                    "message": (
                        f"{r.label}: refresh_token мёртв — сделай grok login "
                        f"пока JWT жив ({(r.meta or {}).get('token_left') or '?'})"
                    ),
                }
            )

    # sort profiles: critical first among live, then by remaining
    def sort_key(p: dict) -> tuple:
        order = {"critical": 0, "warn": 1, "ok": 2, "unknown": 3, "offline": 4}
        rem = (p.get("primary") or {}).get("remaining_pct")
        return (order.get(p["urgency"], 9), rem if rem is not None else 999)

    profiles.sort(key=sort_key)
    alerts.sort(key=lambda a: {"critical": 0, "warn": 1, "offline": 2}.get(a["level"], 9))

    live_n = sum(1 for r in results if r.status == Status.LIVE)
    crit_n = sum(1 for a in alerts if a["level"] == "critical")
    warn_n = sum(1 for a in alerts if a["level"] == "warn")

    ranked = [
        p
        for p in profiles
        if p.get("primary") and p["urgency"] in ("ok", "warn", "critical")
    ]
    tightest = None
    if ranked:
        t = min(ranked, key=lambda p: p["primary"]["remaining_pct"])
        tightest = {
            "id": t["id"],
            "label": t["label"],
            "remaining_pct": t["primary"]["remaining_pct"],
            "period": t["primary"]["period"],
            "reset_at": t["primary"].get("reset_at"),
            "urgency": t["urgency"],
        }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "subscription_usage",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "wall_ms": round(wall_ms, 1),
        "summary": {
            "profiles_total": len(results),
            "profiles_live": live_n,
            "alerts_critical": crit_n,
            "alerts_warn": warn_n,
            "tightest": tightest,
        },
        "alerts": alerts,
        "profiles": profiles,
        "meta": meta or {},
    }


def exit_code_from_payload(payload: dict[str, Any]) -> int:
    """
    0 = all live profiles ok (or no live but no crit)
    1 = warn threshold
    2 = critical remaining
    3 = no live profiles at all (all offline/auth)
    """
    live = payload["summary"]["profiles_live"]
    if live == 0:
        return 3
    if payload["summary"]["alerts_critical"] > 0:
        return 2
    if payload["summary"]["alerts_warn"] > 0:
        return 1
    return 0
