from panel import history


def test_attach_history_skips_profile_without_current_measurement(monkeypatch) -> None:
    payload = {
        "profiles": [
            {
                "id": "claude-default",
                "status": "dead",
                "primary": None,
            }
        ]
    }
    monkeypatch.setattr(
        history,
        "load_series",
        lambda profile_id: [{"remaining_pct": 0.0}],
    )

    history.attach_history(payload)

    assert payload["profiles"][0]["history"] == []
