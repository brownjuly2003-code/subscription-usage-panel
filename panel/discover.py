"""Auto-discover multi-provider profile homes + env-based virtual profiles."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from panel.config import ProfileCfg

# family -> (home name prefix, credential file that must exist)
KNOWN: list[tuple[str, str, str]] = [
    ("claude", ".claude", ".credentials.json"),
    ("codex", ".codex", "auth.json"),
    ("grok", ".grok", "auth.json"),
    ("gemini", ".gemini", ""),  # oauth optional; env also works
    ("kimi", ".kimi", ""),
    ("kimi", ".kimi-code", ""),
    ("openrouter", ".openrouter", ""),
    ("github", ".github-sup", ""),  # optional home for token file
    ("openai", ".openai", ""),
]

SKIP_RE = re.compile(
    r"(cold_archive|archive|bak|backup|tmp|temp|personal-personal)",
    re.I,
)

ENV_PROFILES: list[tuple[str, str, tuple[str, ...]]] = [
    # family, id_suffix, env keys (any)
    ("openrouter", "env", ("OPENROUTER_API_KEY",)),
    ("kimi", "env", ("KIMI_API_KEY", "MOONSHOT_API_KEY")),
    ("gemini", "env", ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY")),
    ("github", "env", ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT")),
    ("openai", "env", ("OPENAI_API_KEY",)),
]


def _suffix_label(home_name: str, prefix: str) -> str:
    if home_name == prefix:
        return "default"
    if home_name.startswith(prefix + "-"):
        return home_name[len(prefix) + 1 :] or "default"
    if home_name.startswith(prefix + "_"):
        return home_name[len(prefix) + 1 :] or "default"
    return home_name


def _home_has_signal(home: Path, family: str, cred: str) -> bool:
    if cred and (home / cred).is_file():
        return True
    # family-specific loose signals
    if family == "gemini":
        return any(
            (home / n).exists()
            for n in (
                "oauth_creds.json",
                "google_accounts.json",
                "credentials.json",
                "auth.json",
                "GEMINI.md",
            )
        )
    if family == "kimi":
        return any(
            (home / n).exists()
            for n in (
                "kimi.json",
                "auth.json",
                "credentials.json",
                "credentials",
            )
        )
    if family in ("openrouter", "openai", "github"):
        return any((home / n).is_file() for n in ("key", "api_key", "token", "auth.json"))
    return False


def discover_profiles(user_home: Path | None = None) -> list[ProfileCfg]:
    root = user_home or Path.home()
    found: list[ProfileCfg] = []
    seen_ids: set[str] = set()

    try:
        entries = list(root.iterdir())
    except OSError:
        entries = []

    for family, prefix, cred in KNOWN:
        for p in entries:
            if not p.is_dir():
                continue
            name = p.name
            if name != prefix and not name.startswith(prefix + "-") and not name.startswith(
                prefix + "_"
            ):
                continue
            if SKIP_RE.search(name):
                continue
            if not _home_has_signal(p, family, cred):
                continue
            suffix = _suffix_label(name, prefix)
            pid = f"{family}-{suffix}".lower().replace(" ", "-")
            if pid in seen_ids:
                pid = f"{family}-{name}".lower().replace(" ", "-")
            seen_ids.add(pid)
            found.append(
                ProfileCfg(
                    id=pid,
                    family=family,
                    label=f"{family.upper()}/{suffix}",
                    home=p,
                    enabled=True,
                )
            )

    # env-only virtual profiles (no dedicated home)
    for family, suffix, envs in ENV_PROFILES:
        if not any(os.environ.get(e) for e in envs):
            continue
        pid = f"{family}-{suffix}"
        if pid in seen_ids:
            continue
        # prefer existing discovered family home
        if any(p.family == family for p in found):
            continue
        vhome = root / f".{family}"
        seen_ids.add(pid)
        found.append(
            ProfileCfg(
                id=pid,
                family=family,
                label=f"{family.upper()}/{suffix}",
                home=vhome if vhome.is_dir() else root / f".sup-{family}",
                enabled=True,
            )
        )

    # gh CLI token without home
    hosts = Path.home() / ".config" / "gh" / "hosts.yml"
    if hosts.is_file() and "github-env" not in seen_ids and not any(
        p.family == "github" for p in found
    ):
        found.append(
            ProfileCfg(
                id="github-gh",
                family="github",
                label="GITHUB/gh",
                home=hosts.parent,
                enabled=True,
            )
        )

    order = {
        "claude": 0,
        "codex": 1,
        "grok": 2,
        "gemini": 3,
        "kimi": 4,
        "openrouter": 5,
        "openai": 6,
        "github": 7,
    }
    found.sort(key=lambda x: (order.get(x.family, 50), x.label.lower()))
    return found


def merge_profiles(
    explicit: Iterable[ProfileCfg],
    discovered: Iterable[ProfileCfg],
) -> list[ProfileCfg]:
    by_id: dict[str, ProfileCfg] = {}
    by_home: dict[str, ProfileCfg] = {}

    for p in discovered:
        by_id[p.id] = p
        try:
            by_home[str(p.home.resolve())] = p
        except OSError:
            by_home[str(p.home)] = p

    for p in explicit:
        try:
            key = str(p.home.resolve())
        except OSError:
            key = str(p.home)
        if key in by_home:
            old = by_home[key]
            by_id.pop(old.id, None)
        by_id[p.id] = p
        by_home[key] = p

    order = {
        "claude": 0,
        "codex": 1,
        "grok": 2,
        "gemini": 3,
        "kimi": 4,
        "openrouter": 5,
        "openai": 6,
        "github": 7,
    }
    out = list(by_id.values())
    out.sort(key=lambda x: (order.get(x.family, 50), x.label.lower()))
    return out


def register_family(
    family: str,
    home_prefix: str,
    credential_file: str,
) -> None:
    fam = family.lower().strip()
    for i, (f, pref, _) in enumerate(KNOWN):
        if f == fam and pref == home_prefix:
            KNOWN[i] = (fam, home_prefix, credential_file)
            return
    KNOWN.append((fam, home_prefix, credential_file))
