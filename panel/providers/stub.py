"""Generic stub for catalog families without a full fetcher yet."""
from __future__ import annotations

import time
from pathlib import Path

import httpx

from panel.catalog import family_meta
from panel.models import ProfileResult, Status


def make_stub(family: str):
    def fetch_stub(
        profile_id: str,
        label: str,
        home: Path,
        client: httpx.Client,
        timeout: float,
    ) -> ProfileResult:
        t0 = time.perf_counter()
        meta = family_meta(family)
        note = meta.get("notes") or meta.get("label") or family
        r = ProfileResult(
            id=profile_id,
            family=family,
            label=label,
            status=Status.DEAD,
            reason=(
                f"provider '{family}' detected but fetcher not implemented yet — "
                f"see docs/PROVIDERS.md ({note})"
            ),
            plan=str(meta.get("label") or family),
        )
        r.meta["optional_fetcher"] = True
        r.meta["catalog_notes"] = note
        r.latency_ms = (time.perf_counter() - t0) * 1000
        return r

    fetch_stub.__name__ = f"fetch_{family}_stub"
    return fetch_stub
