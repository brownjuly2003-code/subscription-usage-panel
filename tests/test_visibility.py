from pathlib import Path

from panel.config import AppConfig, ProfileCfg
from panel.fetch import fetch_all
from panel.models import ProfileResult, Status, Window


def test_fetch_all_only_live_excludes_stale_and_dead(monkeypatch) -> None:
    profiles = [
        ProfileCfg("live", "claude", "CLAUDE/live", Path("live")),
        ProfileCfg("stale", "claude", "CLAUDE/stale", Path("stale")),
        ProfileCfg("dead", "claude", "CLAUDE/dead", Path("dead")),
    ]
    cfg = AppConfig(profiles=profiles, workers=1, only_live=True)

    def fake_fetch_one(profile, client, timeout):
        if profile.id == "live":
            return ProfileResult(
                id=profile.id,
                family=profile.family,
                label=profile.label,
                status=Status.LIVE,
                windows=[Window("7d", used_pct=25, rem_pct=75)],
            )
        if profile.id == "stale":
            return ProfileResult(
                id=profile.id,
                family=profile.family,
                label=profile.label,
                status=Status.STALE,
                windows=[Window("7d", used_pct=50, rem_pct=50)],
            )
        return ProfileResult(
            id=profile.id,
            family=profile.family,
            label=profile.label,
            status=Status.DEAD,
            reason="expired",
        )

    monkeypatch.setattr("panel.fetch.fetch_one", fake_fetch_one)

    results, _ = fetch_all(cfg)

    assert [result.id for result in results] == ["live"]
