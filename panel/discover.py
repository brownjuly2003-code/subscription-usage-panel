"""Scalable multi-provider discovery from catalog + env + explicit config."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from panel.catalog import load_catalog
from panel.config import ProfileCfg


def _suffix_label(home_name: str, prefix: str) -> str:
    if home_name == prefix:
        return "default"
    if home_name.startswith(prefix + "-"):
        return home_name[len(prefix) + 1 :] or "default"
    if home_name.startswith(prefix + "_"):
        return home_name[len(prefix) + 1 :] or "default"
    # nested like .config/github-copilot → use last segment
    if "/" in prefix or "\\" in prefix:
        base = Path(prefix).name
        if home_name == base:
            return "default"
    return home_name


def _matches_prefix(dir_name: str, prefix: str) -> bool:
    """Match .codex, .codex-work; also last segment of .config/foo."""
    if "/" in prefix or "\\" in prefix:
        # handled by nested discover
        return False
    return dir_name == prefix or dir_name.startswith(prefix + "-") or dir_name.startswith(
        prefix + "_"
    )


def _has_any(home: Path, names: list[str]) -> bool:
    for n in names:
        if (home / n).exists():
            return True
    return False


def _home_eligible(home: Path, meta: dict) -> bool:
    creds = list(meta.get("credential_files") or [])
    soft = list(meta.get("soft_files") or [])
    if creds and _has_any(home, creds):
        return True
    if soft and _has_any(home, soft):
        return True
    # empty credential list + dir exists → weak signal only if soft empty
    if not creds and not soft:
        return home.is_dir()
    return False


def discover_profiles(user_home: Path | None = None) -> list[ProfileCfg]:
    root = user_home or Path.home()
    cat = load_catalog()
    families: dict = cat.get("families") or {}
    skip_re = re.compile(cat.get("skip_home_name_regex") or r"$a", re.I)

    found: list[ProfileCfg] = []
    seen_ids: set[str] = set()

    try:
        top = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        top = []

    # index top-level names
    top_by_name = {p.name: p for p in top}

    for family, meta in families.items():
        prefixes = list(meta.get("home_prefixes") or [])
        for prefix in prefixes:
            # Nested under ~/.config/...
            if "/" in prefix or "\\" in prefix:
                base = root / prefix.replace("\\", "/")
                # also allow ~/.config/foo-* siblings
                parent = base.parent
                name = base.name
                candidates: list[Path] = []
                if base.is_dir():
                    candidates.append(base)
                if parent.is_dir():
                    try:
                        for p in parent.iterdir():
                            if p.is_dir() and (
                                p.name == name
                                or p.name.startswith(name + "-")
                                or p.name.startswith(name + "_")
                            ):
                                candidates.append(p)
                    except OSError:
                        pass
                for p in candidates:
                    if skip_re.search(p.name):
                        continue
                    if not _home_eligible(p, meta):
                        continue
                    suffix = _suffix_label(p.name, name)
                    pid = f"{family}-{suffix}".lower().replace(" ", "-")
                    if pid in seen_ids:
                        pid = f"{family}-{p.name}".lower().replace(" ", "-")
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
                continue

            # Top-level ~/.family, ~/.family-*
            for dirname, p in top_by_name.items():
                if not _matches_prefix(dirname, prefix):
                    continue
                if skip_re.search(dirname):
                    continue
                if not _home_eligible(p, meta):
                    continue
                suffix = _suffix_label(dirname, prefix)
                pid = f"{family}-{suffix}".lower().replace(" ", "-")
                if pid in seen_ids:
                    pid = f"{family}-{dirname}".lower().replace(" ", "-")
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

        # Env virtual profile if no home for family
        env_keys = list(meta.get("env_keys") or [])
        if env_keys and any(os.environ.get(k) for k in env_keys):
            if not any(x.family == family for x in found):
                pid = f"{family}-env"
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    vhome = root / f".{family}"
                    found.append(
                        ProfileCfg(
                            id=pid,
                            family=family,
                            label=f"{family.upper()}/env",
                            home=vhome if vhome.is_dir() else root / f".sup-{family}",
                            enabled=True,
                        )
                    )

        # gh hosts.yml special
        if meta.get("gh_hosts"):
            hosts = Path.home() / ".config" / "gh" / "hosts.yml"
            if hosts.is_file() and not any(x.family == family for x in found):
                pid = f"{family}-gh"
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    found.append(
                        ProfileCfg(
                            id=pid,
                            family=family,
                            label=f"{family.upper()}/gh",
                            home=hosts.parent,
                            enabled=True,
                        )
                    )

    # stable order by catalog key order then label
    order = {fam: i for i, fam in enumerate(families.keys())}
    found.sort(key=lambda x: (order.get(x.family, 999), x.label.lower()))
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

    cat = load_catalog()
    families = list((cat.get("families") or {}).keys())
    order = {fam: i for i, fam in enumerate(families)}
    out = list(by_id.values())
    out.sort(key=lambda x: (order.get(x.family, 999), x.label.lower()))
    return out


def register_family(
    family: str,
    home_prefix: str,
    credential_file: str,
) -> None:
    """Runtime extension of catalog (plugins)."""
    cat = load_catalog()
    fams = cat.setdefault("families", {})
    meta = fams.setdefault(family.lower().strip(), {})
    prefs = list(meta.get("home_prefixes") or [])
    if home_prefix not in prefs:
        prefs.append(home_prefix)
    meta["home_prefixes"] = prefs
    creds = list(meta.get("credential_files") or [])
    if credential_file and credential_file not in creds:
        creds.append(credential_file)
    meta["credential_files"] = creds
    # bust cache
    load_catalog.cache_clear()
