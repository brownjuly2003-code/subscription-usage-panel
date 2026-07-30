from pathlib import Path

from panel.catalog import all_families, load_catalog
from panel.discover import discover_profiles
from panel.providers import known_families


def test_catalog_has_many_families():
    fams = all_families()
    assert len(fams) >= 12
    for need in ("claude", "codex", "grok", "gemini", "cursor", "copilot"):
        assert need in fams


def test_every_catalog_family_has_fetcher():
    for fam in all_families():
        assert fam in known_families()


def test_discover_scales_many_homes(tmp_path: Path, monkeypatch):
    for e in (
        "OPENROUTER_API_KEY",
        "KIMI_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
    ):
        monkeypatch.delenv(e, raising=False)

    # simulate many codex + claude homes
    for i in range(30):
        d = tmp_path / f".codex-acct{i}"
        d.mkdir()
        (d / "auth.json").write_text("{}", encoding="utf-8")
    for i in range(20):
        d = tmp_path / f".claude-acct{i}"
        d.mkdir()
        (d / ".credentials.json").write_text("{}", encoding="utf-8")
    # optional family home without fetcher impl → still discoverable via stub
    c = tmp_path / ".cursor"
    c.mkdir()
    (c / "auth.json").write_text("{}", encoding="utf-8")

    found = discover_profiles(tmp_path)
    assert len(found) >= 51
    assert any(p.family == "cursor" for p in found)
    assert sum(1 for p in found if p.family == "codex") == 30
