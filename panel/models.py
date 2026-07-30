from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Status(str, Enum):
    LIVE = "live"
    AUTH = "auth"
    DEAD = "dead"
    STALE = "stale"
    ERROR = "error"


@dataclass
class Window:
    """Subscription usage window (rate-limit / plan pool)."""

    label: str
    used_pct: float  # 0..100+ from provider; real subscription utilization
    rem_pct: float
    reset: str = ""  # relative: 5d10h
    reset_at: str = ""  # absolute local date: 2026-08-05 14:30

    def __post_init__(self) -> None:
        self.used_pct = float(self.used_pct)
        self.rem_pct = float(self.rem_pct)


@dataclass
class ProfileResult:
    id: str
    family: str  # claude | codex | grok
    label: str
    status: Status
    reason: str = ""
    windows: list[Window] = field(default_factory=list)
    plan: str = ""
    email: str = ""
    latency_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def sort_key(self) -> tuple:
        rank = {
            Status.LIVE: 0,
            Status.STALE: 1,
            Status.AUTH: 2,
            Status.ERROR: 3,
            Status.DEAD: 4,
        }[self.status]
        max_u = max((w.used_pct for w in self.windows), default=-1.0)
        return (rank, -max_u, self.label.lower())
