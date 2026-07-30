from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from panel.catalog import family_rgb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
EXAMPLE_CONFIG = ROOT / "config.example.yaml"
CACHE_DIR = ROOT / ".cache"


@dataclass
class ProfileCfg:
    id: str
    family: str
    label: str
    home: Path
    enabled: bool = True


@dataclass
class AppConfig:
    interval: int = 60
    timeout_s: float = 8.0
    workers: int = 16  # scale for many profiles
    show_dead: bool = True
    cache_ttl_s: int = 45
    bar_width: int = 5
    auto_discover: bool = True
    theme: str = "dark"
    only_live: bool = False
    families_filter: list[str] = field(default_factory=list)
    profiles_filter: list[str] = field(default_factory=list)
    colors: dict[str, str] = field(default_factory=dict)
    profiles: list[ProfileCfg] = field(default_factory=list)


def expand_home(raw: str) -> Path:
    s = (raw or "").strip()
    if s.startswith("~/") or s == "~":
        return Path.home() / s[2:] if s.startswith("~/") else Path.home()
    if s.startswith("~\\"):
        return Path.home() / s[2:]
    return Path(s).expanduser()


def _apply_filters(cfg: AppConfig) -> None:
    profs = list(cfg.profiles)
    if cfg.families_filter:
        allow = {f.lower() for f in cfg.families_filter}
        profs = [p for p in profs if p.family.lower() in allow]
    if cfg.profiles_filter:
        allow_p = {x.lower() for x in cfg.profiles_filter}
        profs = [
            p
            for p in profs
            if p.id.lower() in allow_p or p.label.lower() in allow_p
        ]
    cfg.profiles = profs


def load_config(path: Path | None = None) -> AppConfig:
    from panel.discover import discover_profiles, merge_profiles

    cfg_path = path or DEFAULT_CONFIG
    if not cfg_path.is_file() and EXAMPLE_CONFIG.is_file() and path is None:
        cfg_path = EXAMPLE_CONFIG

    data: dict[str, Any] = {}
    if cfg_path.is_file():
        with cfg_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    explicit: list[ProfileCfg] = []
    for p in data.get("profiles") or []:
        explicit.append(
            ProfileCfg(
                id=str(p["id"]),
                family=str(p["family"]).lower(),
                label=str(p.get("label") or p["id"]),
                home=expand_home(str(p["home"])),
                enabled=bool(p.get("enabled", True)),
            )
        )

    auto = bool(data.get("auto_discover", True))
    if auto:
        profiles = merge_profiles(explicit, discover_profiles())
    else:
        profiles = explicit

    theme = str(data.get("theme") or "dark").lower()
    if theme not in ("dark", "light"):
        theme = "dark"

    colors = family_rgb()
    colors.update(dict(data.get("colors") or {}))

    fam_f = data.get("families") or data.get("families_filter") or []
    if isinstance(fam_f, str):
        fam_f = [x.strip() for x in fam_f.split(",") if x.strip()]
    prof_f = data.get("profile_filter") or data.get("profiles_filter") or []
    if isinstance(prof_f, str):
        prof_f = [x.strip() for x in prof_f.split(",") if x.strip()]

    cfg = AppConfig(
        interval=max(15, int(data.get("interval", 60))),
        timeout_s=float(data.get("timeout_s", 8)),
        workers=max(1, min(64, int(data.get("workers", 16)))),
        show_dead=bool(data.get("show_dead", True)),
        cache_ttl_s=int(data.get("cache_ttl_s", 45)),
        bar_width=int(data.get("bar_width", 5)),
        auto_discover=auto,
        theme=theme,
        only_live=bool(data.get("only_live", False)),
        families_filter=[str(x).lower() for x in fam_f],
        profiles_filter=[str(x) for x in prof_f],
        colors=colors,
        profiles=profiles,
    )
    _apply_filters(cfg)
    return cfg
