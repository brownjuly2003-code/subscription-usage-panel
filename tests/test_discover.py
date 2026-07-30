from pathlib import Path

from panel.discover import discover_profiles, merge_profiles
from panel.config import ProfileCfg


def test_discover_finds_known_families(tmp_path: Path):
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".codex-work").mkdir()
    (tmp_path / ".codex-work" / "auth.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".credentials.json").write_text("{}", encoding="utf-8")
    # no auth — skip
    (tmp_path / ".grok").mkdir()

    found = discover_profiles(tmp_path)
    ids = {p.id for p in found}
    assert "codex-default" in ids
    assert "codex-work" in ids
    assert "claude-default" in ids
    assert not any(p.family == "grok" for p in found)


def test_merge_explicit_wins():
    d = [
        ProfileCfg("codex-default", "codex", "CODEX/default", Path("/a/.codex")),
    ]
    e = [
        ProfileCfg(
            "codex-default",
            "codex",
            "CODEX/main",
            Path("/a/.codex"),
            enabled=True,
        )
    ]
    m = merge_profiles(e, d)
    assert len(m) == 1
    assert m[0].label == "CODEX/main"
