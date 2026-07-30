"""Provider registry — plug in new subscription sources here."""
from __future__ import annotations

from typing import Callable

from .claude import fetch_claude
from .codex import fetch_codex
from .grok import fetch_grok

# family -> fetch(profile_id, label, home, client, timeout) -> ProfileResult
FETCHERS: dict[str, Callable] = {
    "claude": fetch_claude,
    "codex": fetch_codex,
    "grok": fetch_grok,
}


def register_provider(family: str, fetcher: Callable) -> None:
    """Register or override a provider family (for plugins / forks)."""
    FETCHERS[family.lower().strip()] = fetcher


def known_families() -> list[str]:
    return sorted(FETCHERS.keys())
