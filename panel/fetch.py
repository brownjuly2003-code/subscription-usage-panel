from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import httpx

from panel.config import AppConfig, ProfileCfg
from panel.models import ProfileResult, Status
from panel.providers import FETCHERS


def fetch_one(
    p: ProfileCfg, client: httpx.Client, timeout: float
) -> ProfileResult:
    fetcher = FETCHERS.get(p.family)
    if not fetcher:
        return ProfileResult(
            id=p.id,
            family=p.family,
            label=p.label,
            status=Status.ERROR,
            reason=f"unknown family: {p.family} (register_provider?)",
        )
    return fetcher(p.id, p.label, p.home, client, timeout)


def fetch_all(cfg: AppConfig) -> tuple[list[ProfileResult], float]:
    enabled = [p for p in cfg.profiles if p.enabled]
    results: list[ProfileResult] = []
    t0 = time.perf_counter()

    # httpx Client is not fully thread-safe for all ops; use one client per worker call
    # via separate short-lived clients, or a lock. Simpler: each task owns a client.
    def _job(p: ProfileCfg) -> ProfileResult:
        with httpx.Client(follow_redirects=True) as client:
            return fetch_one(p, client, cfg.timeout_s)

    with ThreadPoolExecutor(max_workers=cfg.workers) as ex:
        futs = {ex.submit(_job, p): p for p in enabled}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                p = futs[fut]
                results.append(
                    ProfileResult(
                        id=p.id,
                        family=p.family,
                        label=p.label,
                        status=Status.ERROR,
                        reason=f"crash: {type(e).__name__}",
                    )
                )

    wall = (time.perf_counter() - t0) * 1000
    results.sort(key=lambda r: r.sort_key)
    return results, wall
