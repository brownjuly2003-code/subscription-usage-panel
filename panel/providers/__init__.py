"""Provider registry — popular subscription / quota sources."""
from __future__ import annotations

from typing import Callable

from .claude import fetch_claude
from .codex import fetch_codex
from .gemini import fetch_gemini
from .github import fetch_github
from .grok import fetch_grok
from .kimi import fetch_kimi
from .openai_api import fetch_openai_api
from .openrouter import fetch_openrouter

FETCHERS: dict[str, Callable] = {
    "claude": fetch_claude,
    "codex": fetch_codex,
    "grok": fetch_grok,
    "gemini": fetch_gemini,
    "kimi": fetch_kimi,
    "openrouter": fetch_openrouter,
    "openai": fetch_openai_api,
    "github": fetch_github,
}


def register_provider(family: str, fetcher: Callable) -> None:
    FETCHERS[family.lower().strip()] = fetcher


def known_families() -> list[str]:
    return sorted(FETCHERS.keys())
