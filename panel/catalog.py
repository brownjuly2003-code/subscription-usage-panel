"""Load declarative provider catalog (scalable multi-network registry)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.yaml"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        return {"version": 1, "families": {}, "skip_home_name_regex": ""}
    with CATALOG_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("families", {})
    data.setdefault("skip_home_name_regex", "")
    return data


def family_meta(family: str) -> dict[str, Any]:
    cat = load_catalog()
    return dict((cat.get("families") or {}).get(family, {}))


def all_families() -> dict[str, dict[str, Any]]:
    return dict(load_catalog().get("families") or {})


def family_colors() -> dict[str, str]:
    out = {}
    for fam, meta in all_families().items():
        if meta.get("color"):
            out[fam] = meta["color"]
    return out


def family_rgb() -> dict[str, str]:
    out = {}
    for fam, meta in all_families().items():
        if meta.get("color_rgb"):
            out[fam] = meta["color_rgb"]
    return out
