import re

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
    # extract first panel-stat body
    m = re.search(r'class="panel panel-stat">(.*?)</div>\s*</div>\s*</div>', html, re.S)
    assert m
    body = m.group(1)
    assert body.count("2026-08-05 00:09") == 1
    assert len(re.findall(r"\bweek\b", body, re.I)) == 1
    # only the human label "remaining · week", not title attrs spam
    assert len(re.findall(r"stat-title\">remaining", body)) == 1
    assert "themeToggle" in html
    assert 'data-theme="dark"' in html
