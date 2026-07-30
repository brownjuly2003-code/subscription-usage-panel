"""Provider registry — built-ins + catalog stubs for optional families."""
from __future__ import annotations

from typing import Callable

from panel.catalog import all_families

from .claude import fetch_claude
from .codex import fetch_codex
from .gemini import fetch_gemini
from .github import fetch_github
from .grok import fetch_grok
from .kimi import fetch_kimi
from .openai_api import fetch_openai_api
from .openrouter import fetch_openrouter
from .stub import make_stub

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


def _ensure_catalog_stubs() -> None:
    for fam, meta in all_families().items():
        if fam in FETCHERS:
            continue
        # optional / not-yet-implemented families still discoverable
        FETCHERS[fam] = make_stub(fam)


_ensure_catalog_stubs()


def register_provider(family: str, fetcher: Callable) -> None:
    FETCHERS[family.lower().strip()] = fetcher


def known_families() -> list[str]:
    _ensure_catalog_stubs()
    return sorted(FETCHERS.keys())
