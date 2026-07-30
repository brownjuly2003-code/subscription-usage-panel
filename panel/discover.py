"""Auto-discover multi-provider profile homes under the user directory."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from panel.config import ProfileCfg

# family -> (home name prefix, credential file that must exist)
KNOWN: list[tuple[str, str, str]] = [
    ("claude", ".claude", ".credentials.json"),
    ("codex", ".codex", "auth.json"),
    ("grok", ".grok", "auth.json"),
]

# skip junk / archives
SKIP_RE = re.compile(
    r"(cold_archive|archive|bak|backup|tmp|temp|personal-personal)",
    re.I,
)


def _suffix_label(home_name: str, prefix: str) -> str:
    """~/.codex-work → work; ~/.codex → default; ~/.claude-work → work."""
    if home_name == prefix:
        return "default"
    if home_name.startswith(prefix + "-"):
        return home_name[len(prefix) + 1 :] or "default"
    if home_name.startswith(prefix + "_"):
        return home_name[len(prefix) + 1 :] or "default"
    return home_name


def discover_profiles(user_home: Path | None = None) -> list[ProfileCfg]:
    root = user_home or Path.home()
    found: list[ProfileCfg] = []
    seen_ids: set[str] = set()

    try:
        entries = list(root.iterdir())
    except OSError:
        return []

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
            if not (p / cred).is_file():
                continue
            suffix = _suffix_label(name, prefix)
            pid = f"{family}-{suffix}".lower().replace(" ", "-")
            if pid in seen_ids:
                pid = f"{family}-{name}".lower().replace(" ", "-")
            seen_ids.add(pid)
            label = f"{family.upper()}/{suffix}"
            found.append(
                ProfileCfg(
                    id=pid,
                    family=family,
                    label=label,
                    home=p,
                    enabled=True,
                )
            )

    # stable order: family then label
    order = {"claude": 0, "codex": 1, "grok": 2}
    found.sort(key=lambda x: (order.get(x.family, 9), x.label.lower()))
    return found


def merge_profiles(
    explicit: Iterable[ProfileCfg],
    discovered: Iterable[ProfileCfg],
) -> list[ProfileCfg]:
    """Explicit config wins on same id; discovery fills the rest."""
    by_id: dict[str, ProfileCfg] = {}
    by_home: dict[str, ProfileCfg] = {}

    for p in discovered:
        by_id[p.id] = p
        by_home[str(p.home.resolve())] = p

    for p in explicit:
        key = str(p.home.resolve()) if p.home.exists() else str(p.home)
        # remove discovery entry with same home
        if key in by_home:
            old = by_home[key]
            by_id.pop(old.id, None)
        by_id[p.id] = p
        by_home[key] = p

    order = {"claude": 0, "codex": 1, "grok": 2}
    out = list(by_id.values())
    out.sort(key=lambda x: (order.get(x.family, 9), x.label.lower()))
    return out


def register_family(
    family: str,
    home_prefix: str,
    credential_file: str,
) -> None:
    """Allow third-party / future providers to plug into discovery."""
    fam = family.lower().strip()
    for i, (f, _, _) in enumerate(KNOWN):
        if f == fam:
            KNOWN[i] = (fam, home_prefix, credential_file)
            return
    KNOWN.append((fam, home_prefix, credential_file))
