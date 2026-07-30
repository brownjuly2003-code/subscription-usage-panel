from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def fmt_diff_seconds(diff: float) -> str:
    if diff <= 0:
        return "now"
    if diff < 60:
        return "<1m"
    d = int(diff // 86400)
    h = int((diff % 86400) // 3600)
    m = int((diff % 3600) // 60)
    if d > 0:
        return f"{d}d{h}h"
    if h > 0:
        return f"{h}h{m}m"
    return f"{m}m"


def _parse_iso_dt(ts: str) -> Optional[datetime]:
    try:
        s = str(ts).replace("Z", "+00:00")
        if "." in s:
            head, rest = s.split(".", 1)
            digits = "".join(c for c in rest if c.isdigit())[:6]
            tz = ""
            for i, ch in enumerate(rest):
                if not ch.isdigit():
                    tz = rest[i:]
                    break
            s = f"{head}.{digits}{tz or '+00:00'}"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def format_absolute_local(dt: datetime) -> str:
    """UTC datetime → local wall time string."""
    local = dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M")


def format_reset_iso(ts: Optional[str]) -> str:
    if not ts or ts == "null":
        return ""
    dt = _parse_iso_dt(str(ts))
    if not dt:
        return ""
    return fmt_diff_seconds((dt - datetime.now(timezone.utc)).total_seconds())


def format_reset_at_iso(ts: Optional[str]) -> str:
    if not ts or ts == "null":
        return ""
    dt = _parse_iso_dt(str(ts))
    if not dt:
        return ""
    return format_absolute_local(dt)


def format_reset_epoch(epoch: Optional[float | int | str]) -> str:
    if epoch is None or epoch == "" or epoch == "null":
        return ""
    try:
        e = float(epoch)
    except (TypeError, ValueError):
        return ""
    if e <= 0:
        return ""
    if e > 1e12:
        e /= 1000.0
    return fmt_diff_seconds(e - datetime.now(timezone.utc).timestamp())


def format_reset_at_epoch(epoch: Optional[float | int | str]) -> str:
    if epoch is None or epoch == "" or epoch == "null":
        return ""
    try:
        e = float(epoch)
    except (TypeError, ValueError):
        return ""
    if e <= 0:
        return ""
    if e > 1e12:
        e /= 1000.0
    dt = datetime.fromtimestamp(e, tz=timezone.utc)
    return format_absolute_local(dt)


def window_label_seconds(secs: Optional[float | int]) -> str:
    try:
        s = int(secs or 0)
    except (TypeError, ValueError):
        return "win"
    return {18000: "5h", 86400: "1d", 604800: "7d"}.get(
        s, f"{s // 3600}h" if s >= 3600 else f"{s}s"
    )


def parse_pct(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt_pct(p: float, digits: int = 2) -> str:
    if abs(p - round(p)) < 1e-9:
        return f"{int(round(p))}%"
    s = f"{p:.{digits}f}".rstrip("0").rstrip(".")
    return f"{s}%"
