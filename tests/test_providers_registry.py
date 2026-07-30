from panel.providers import FETCHERS, known_families


def test_popular_families_registered():
    fams = set(known_families())
    for need in (
        "claude",
        "codex",
        "grok",
        "gemini",
        "kimi",
        "openrouter",
        "openai",
        "github",
    ):
        assert need in fams
        assert callable(FETCHERS[need])
