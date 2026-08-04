from panel.html_dash import render_dashboard_html
from panel.models import ProfileResult, Status, Window


def test_no_duplicate_week_or_date_in_panel():
    r = ProfileResult(
        id="codex-work",
        family="codex",
        label="CODEX/work",
        status=Status.LIVE,
        plan="prolite",
        windows=[
            Window(
                "7d",
                used_pct=95,
                rem_pct=5,
                reset="5d10h",
                reset_at="2026-08-05 00:09",
            )
        ],
    )
    html = render_dashboard_html([r], 10.0, theme="dark", live=False)
    # Only the visible panel body before footer/script
    start = html.find('data-label="codex/work"')
    assert start > 0
    end = html.find("Offline / auth", start)
    if end < 0:
        end = html.find("<script", start)
    body = html[start:end]
    assert body.count("2026-08-05 00:09") == 1
    # Period legend is global (once); cards must not spam "remaining · week" / used %
    assert "Weekly limit remaining" in html
    assert "remaining · week" not in body
    assert "used " not in body
    assert body.lower().count("week") == 0
    # File-mode badge is data cadence, not a fake 60s "auto" fetch
    assert "Auto · 60s" not in html
    assert "Data · 5m" in html
    assert "themeToggle" in html
    assert 'data-theme="dark"' in html
    assert "profileSearch" in html
    assert "chip-filter" in html


def test_live_badge_uses_poll_seconds():
    r = ProfileResult(
        id="grok-work",
        family="grok",
        label="GROK/work",
        status=Status.LIVE,
        windows=[Window("7d", used_pct=50, rem_pct=50, reset="2d", reset_at="")],
    )
    html = render_dashboard_html(
        [r], 10.0, theme="dark", live=True, poll_seconds=60
    )
    assert "Live · 1m" in html  # 60s → compact 1m
    assert "Auto · 60s" not in html
    assert "Weekly limit remaining" in html
