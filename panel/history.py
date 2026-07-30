"""Local history of remaining % for real sparklines (not synthetic)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from panel.config import ROOT

HISTORY_DIR = ROOT / ".cache" / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
MAX_POINTS = 96  # ~24h if snap every 15m; fine for shorter too


def _path(profile_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in profile_id)
    return HISTORY_DIR / f"{safe}.jsonl"


def append_snapshot(profiles: list[dict[str, Any]]) -> None:
    """Append one point per profile that has primary remaining."""
    ts = time.time()
    for p in profiles:
        prim = p.get("primary")
        if not prim or prim.get("remaining_pct") is None:
            continue
        rec = {
            "ts": ts,
            "remaining_pct": prim["remaining_pct"],
            "used_pct": prim.get("used_pct"),
            "period": prim.get("period"),
        }
        path = _path(p["id"])
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _trim(path)


def _trim(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= MAX_POINTS:
        return
    path.write_text("\n".join(lines[-MAX_POINTS:]) + "\n", encoding="utf-8")


def load_series(profile_id: str, limit: int = 48) -> list[dict[str, Any]]:
    path = _path(profile_id)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out[-limit:]


def attach_history(payload: dict[str, Any]) -> dict[str, Any]:
    """Mutate payload profiles with history series for sparklines."""
    for p in payload.get("profiles") or []:
        p["history"] = load_series(p["id"])
    return payload
