"""Grafana-dark replica HTML for subscription remaining (max visual fidelity)."""
from __future__ import annotations

import html
import json
from datetime import datetime
from typing import List

from panel.models import ProfileResult, Status
from panel.timefmt import fmt_pct

# Official-ish Grafana palette (classic colors)
G = {
    "green": "#73BF69",
    "orange": "#FF9830",
    "red": "#F2495C",
    "yellow": "#FADE2A",
    "blue": "#5794F2",
    "purple": "#B877D9",
    "super": "#8AB8FF",
}

def _family_colors() -> dict[str, str]:
    try:
        from panel.catalog import family_colors

        c = family_colors()
        if c:
            return c
    except Exception:
        pass
    return {
        "claude": G["orange"],
        "codex": G["purple"],
        "grok": G["green"],
        "gemini": "#4285F4",
        "kimi": "#00C2A8",
        "openrouter": "#A78BFA",
        "openai": "#10A37F",
        "github": "#8B949E",
    }


FAMILY_COLOR = _family_colors()


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def _threshold_rem(rem: float) -> str:
    """Color by remaining (high=good)."""
    if rem < 20:
        return G["red"]
    if rem < 50:
        return G["orange"]
    return G["green"]


def _window_human(label: str) -> str:
    """Single human label for period — no jargon spam."""
    m = {
        "7d": "week",
        "5h": "5 hours",
        "1d": "day",
        "mo": "month",
        "pool": "period",
    }
    return m.get((label or "").lower(), label or "period")


def _sparkline_svg(
    rem: float,
    color: str,
    history: list | None = None,
    w: int = 280,
    h: int = 48,
) -> str:
    """Sparkline from real history points; if none, honest remaining bar (no fake data)."""
    rem = max(0.0, min(100.0, rem))
    pts: list[float] = []
    if history:
        for pt in history:
            try:
                pts.append(max(0.0, min(100.0, float(pt.get("remaining_pct")))))
            except (TypeError, ValueError, AttributeError):
                continue
    if len(pts) < 2:
        # honest single-value bar: used (gray) | remaining (color)
        used = 100.0 - rem
        return f"""
    <div class="rem-bar" title="remaining {rem:.1f}%">
      <div class="rem-bar-used" style="width:{used:.2f}%"></div>
      <div class="rem-bar-left" style="width:{rem:.2f}%;background:{color}"></div>
    </div>"""

    n = len(pts)

    def xy(i, v):
        x = 2 + (w - 4) * i / (n - 1)
        y = 2 + (h - 4) * (1 - v / 100.0)
        return x, y

    path = []
    for i, v in enumerate(pts):
        x, y = xy(i, v)
        path.append(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}")
    line = " ".join(path)
    x0, _ = xy(0, pts[0])
    xn, _ = xy(n - 1, pts[-1])
    area = f"{line} L{xn:.1f},{h - 1} L{x0:.1f},{h - 1} Z"
    grad_id = f"g{abs(hash((tuple(pts[-8:]), color))) % 10_000_000}"
    return f"""
    <svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="{color}" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="{color}" stop-opacity="0.02"/>
        </linearGradient>
      </defs>
      <path d="{area}" fill="url(#{grad_id})"/>
      <path d="{line}" fill="none" stroke="{color}" stroke-width="1.5" vector-effect="non-scaling-stroke"/>
    </svg>"""


def _cards(results: List[ProfileResult]) -> tuple[list[dict], list[dict]]:
    colors = _family_colors()
    live, offline = [], []
    for r in results:
        color = colors.get(r.family, G["blue"])
        if r.status not in (Status.LIVE, Status.STALE) or not r.windows:
            offline.append(
                {
                    "label": r.label,
                    "family": r.family,
                    "color": color,
                    "status": r.status.value,
                    "reason": r.reason or r.status.value,
                    "plan": r.plan or "—",
                }
            )
            continue
        wins = [
            {
                "label": w.label,
                "used_pct": float(w.used_pct),
                "rem_pct": float(w.rem_pct),
                "reset": w.reset or "—",
                "reset_at": w.reset_at or "",
            }
            for w in r.windows
        ]
        main = [
            w
            for w in wins
            if not (w["used_pct"] <= 0.01 and w["rem_pct"] >= 99.9)
        ] or wins
        primary = min(main, key=lambda x: x["rem_pct"])
        live.append(
            {
                "label": r.label,
                "family": r.family,
                "color": color,
                "plan": r.plan or "",
                "status": r.status.value,
                "primary": primary,
                "windows": main,
            }
        )
    live.sort(key=lambda c: c["primary"]["rem_pct"])
    return live, offline


def render_dashboard_html(
    results: List[ProfileResult],
    wall_ms: float,
    title: str = "Subscription remaining",
    theme: str = "dark",
    live: bool = False,
    poll_seconds: int = 60,
    payload: dict | None = None,
) -> str:
    from panel.history import attach_history, append_snapshot
    from panel.schema import build_payload

    theme = "light" if str(theme).lower() == "light" else "dark"
    live_cards, offline = _cards(results)
    if payload is None:
        payload = build_payload(results, wall_ms, meta={"mode": "html"})
        append_snapshot(payload.get("profiles") or [])
        attach_history(payload)
    alerts = payload.get("alerts") or []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    live_n = sum(1 for r in results if r.status == Status.LIVE)
    total = len(results)
    families_present = sorted({c["family"] for c in live_cards} | {o["family"] for o in offline})
    family_chips = "".join(
        f'<button type="button" class="chip chip-filter" data-family="{_esc(f)}">{_esc(f)}</button>'
        for f in families_present
    )

    # alert strip
    alert_html = ""
    if alerts:
        items = []
        for a in alerts[:8]:
            lvl = a.get("level") or "warn"
            items.append(
                f'<div class="alert-item { _esc(lvl) }">{_esc(a.get("message") or "")}</div>'
            )
        alert_html = f'<div class="alert-strip">{"".join(items)}</div>'

    # --- Stat panels: one fact each field, no duplicate rem/reset ---
    stat_panels = []
    for c in live_cards:
        p = c["primary"]
        rem = p["rem_pct"]
        used = p["used_pct"]
        col = _threshold_rem(rem)
        # map history: cards don't have id — recover from label match in payload
        hist = []
        for pp in payload.get("profiles") or []:
            if pp.get("label") == c["label"] and pp.get("family") == c["family"]:
                hist = pp.get("history") or []
                break
        spark = _sparkline_svg(rem, col, history=hist)
        plan = _esc(c["plan"]) if c["plan"] else ""
        period = _window_human(p.get("label") or "")

        # reset once: absolute date preferred, relative only if no date
        if p.get("reset_at"):
            reset_line = f'reset <b>{_esc(p["reset_at"])}</b>'
            if p.get("reset") and p["reset"] not in ("—", ""):
                reset_line += f' · in {_esc(p["reset"])}'
        elif p.get("reset") and p["reset"] not in ("—", ""):
            reset_line = f'reset in <b>{_esc(p["reset"])}</b>'
        else:
            reset_line = "reset <b>—</b>"

        # extra windows only if different from primary (no re-print of same week)
        extras = []
        for w in c["windows"]:
            if w["label"] == p["label"] and abs(w["rem_pct"] - rem) < 1e-6:
                continue
            wc = _threshold_rem(w["rem_pct"])
            wperiod = _window_human(w["label"])
            if w.get("reset_at"):
                wr = _esc(w["reset_at"])
            elif w.get("reset"):
                wr = f'in {_esc(w["reset"])}'
            else:
                wr = "—"
            extras.append(
                f"""<div class="extra-row">
              <span class="extra-period">{_esc(wperiod)}</span>
              <span class="extra-rem" style="color:{wc}">{_esc(fmt_pct(w['rem_pct'], 2))} left</span>
              <span class="extra-reset">{wr}</span>
            </div>"""
            )

        extras_html = (
            f'<div class="stat-extras">{"".join(extras)}</div>' if extras else ""
        )

        stat_panels.append(
            f"""
      <div class="panel panel-stat" data-family="{_esc(c['family'])}" data-label="{_esc(c['label']).lower()}" data-kind="live">
        <div class="panel-header">
          <div class="panel-title">
            <span class="series-dot" style="background:{c['color']}"></span>
            <span class="panel-title-text">{_esc(c['label'])}</span>
            {f'<span class="panel-desc">{plan}</span>' if plan else ''}
          </div>
          <div class="panel-menu" aria-hidden="true">
            <span></span><span></span><span></span>
          </div>
        </div>
        <div class="panel-content stat-content">
          <div class="stat-value-wrap">
            <div class="stat-value" style="color:{col}">{_esc(fmt_pct(rem, 2))}</div>
            <div class="stat-title">remaining · {_esc(period)}</div>
            <div class="stat-used">used {_esc(fmt_pct(used, 2))}</div>
            <div class="stat-reset">{reset_line}</div>
          </div>
          <div class="stat-graph">
            {spark}
          </div>
          {extras_html}
        </div>
      </div>"""
        )

    if not stat_panels:
        stat_panels.append(
            """
      <div class="panel panel-stat">
        <div class="panel-header"><div class="panel-title"><span class="panel-title-text">No data</span></div></div>
        <div class="panel-content"><div class="empty">No live subscription windows</div></div>
      </div>"""
        )

    # --- Table panel ---
    table_panel = ""
    if offline:
        rows = []
        for o in offline:
            rows.append(
                f"""<tr>
            <td><span class="series-dot" style="background:{o['color']}"></span>{_esc(o['label'])}</td>
            <td class="mono status">{_esc(o['status'])}</td>
            <td class="weak">{_esc(o['reason'])}</td>
            <td class="weak">{_esc(o['plan'])}</td>
          </tr>"""
            )
        table_panel = f"""
    <div class="row row-wide">
      <div class="panel panel-table" data-kind="offline" id="offlinePanel">
        <div class="panel-header">
          <div class="panel-title">
            <span class="panel-title-text">Offline / auth ({len(offline)})</span>
          </div>
          <button type="button" class="gf-btn" id="toggleOffline" style="height:24px;font-size:11px">Collapse</button>
        </div>
        <div class="panel-content table-content" id="offlineBody">
          <table class="gf-table">
            <thead>
              <tr>
                <th>Profile</th>
                <th>Status</th>
                <th>Reason</th>
                <th>Plan</th>
              </tr>
            </thead>
            <tbody>
              {''.join(rows)}
            </tbody>
          </table>
        </div>
      </div>
    </div>"""

    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="{theme}">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=Roboto+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<style>
  /* ========== Grafana-inspired themes ========== */
  html[data-theme="dark"] {{
    --gf-page-bg: #111217;
    --gf-primary-bg: #181b1f;
    --gf-panel-bg: #181b1f;
    --gf-panel-border: #2c3235;
    --gf-strong-bg: #22252b;
    --gf-text-primary: #ccccdc;
    --gf-text-secondary: #8e8e9a;
    --gf-text-disabled: #6e6e76;
    --gf-text-max: #ffffff;
    --gf-border-weak: #2c3235;
    --gf-border-medium: #3d3d42;
    --gf-action: #3d71d9;
    --gf-error: #f2495c;
    --gf-warning: #ff9830;
    --gf-success: #73bf69;
    --gf-sidemenu: #181b1f;
    --gf-sidemenu-border: #2c3235;
    --gf-spark-grid: rgba(255,255,255,0.04);
  }}
  html[data-theme="light"] {{
    --gf-page-bg: #f4f5f5;
    --gf-primary-bg: #ffffff;
    --gf-panel-bg: #ffffff;
    --gf-panel-border: #d8d9da;
    --gf-strong-bg: #e6e6e9;
    --gf-text-primary: #111217;
    --gf-text-secondary: #52545c;
    --gf-text-disabled: #8e8e9a;
    --gf-text-max: #000000;
    --gf-border-weak: #dde4ed;
    --gf-border-medium: #c7c7d0;
    --gf-action: #3d71d9;
    --gf-error: #e02f44;
    --gf-warning: #ff9830;
    --gf-success: #56a64b;
    --gf-sidemenu: #ffffff;
    --gf-sidemenu-border: #d8d9da;
    --gf-spark-grid: rgba(0,0,0,0.04);
  }}
  :root {{
    --gf-font: "Roboto", "Helvetica Neue", Arial, sans-serif;
    --gf-mono: "Roboto Mono", Menlo, Monaco, Consolas, monospace;
  }}

  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0;
    padding: 0;
    height: 100%;
    background: var(--gf-page-bg);
    color: var(--gf-text-primary);
    font-family: var(--gf-font);
    font-size: 14px;
    font-weight: 400;
    -webkit-font-smoothing: antialiased;
  }}
  a {{ color: var(--gf-action); text-decoration: none; }}

  /* ----- App shell: sidemenu + main ----- */
  .app {{
    display: flex;
    min-height: 100vh;
  }}
  .sidemenu {{
    width: 56px;
    flex-shrink: 0;
    background: var(--gf-sidemenu);
    border-right: 1px solid var(--gf-sidemenu-border);
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 12px 0;
    gap: 4px;
  }}
  .side-logo {{
    width: 28px;
    height: 28px;
    border-radius: 4px;
    background: conic-gradient(from 180deg, #F2495C, #FF9830, #FADE2A, #73BF69, #5794F2, #B877D9, #F2495C);
    margin-bottom: 16px;
  }}
  .alert-strip {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
  }}
  .alert-item {{
    font-size: 12px;
    font-weight: 500;
    padding: 4px 10px;
    border-radius: 2px;
    border: 1px solid var(--gf-border-weak);
    background: var(--gf-primary-bg);
  }}
  .alert-item.critical {{
    color: var(--gf-error);
    border-color: var(--gf-error);
  }}
  .alert-item.warn {{
    color: var(--gf-warning);
    border-color: var(--gf-warning);
  }}
  .alert-item.offline {{
    color: var(--gf-text-secondary);
  }}
  .live-dot {{
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--gf-success);
    margin-right: 6px;
    box-shadow: 0 0 0 0 rgba(115,191,105,0.6);
    animation: pulse 2s infinite;
  }}
  @keyframes pulse {{
    0% {{ box-shadow: 0 0 0 0 rgba(115,191,105,0.5); }}
    70% {{ box-shadow: 0 0 0 6px rgba(115,191,105,0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(115,191,105,0); }}
  }}
  .rem-bar {{
    display: flex;
    width: 100%;
    height: 8px;
    background: var(--gf-strong-bg);
    border-radius: 1px;
    overflow: hidden;
    margin-top: 12px;
  }}
  .rem-bar-used {{ height: 100%; background: #52545c; opacity: 0.55; }}
  html[data-theme="light"] .rem-bar-used {{ background: #c7c7d0; opacity: 0.9; }}
  .rem-bar-left {{ height: 100%; }}
  .side-icon {{
    width: 40px;
    height: 40px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--gf-text-secondary);
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.02em;
  }}
  .side-icon.active {{
    background: var(--gf-strong-bg);
    color: var(--gf-text-max);
  }}
  .side-icon:hover {{ background: var(--gf-strong-bg); color: var(--gf-text-primary); }}

  .main {{
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }}

  /* ----- Navbar ----- */
  .navbar {{
    height: 40px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 8px 0 12px;
    background: var(--gf-page-bg);
    border-bottom: 1px solid var(--gf-border-weak);
  }}
  .nav-breadcrumb {{
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 14px;
    color: var(--gf-text-secondary);
    min-width: 0;
  }}
  .nav-breadcrumb .sep {{ color: var(--gf-text-disabled); }}
  .nav-breadcrumb .current {{
    color: var(--gf-text-max);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .nav-spacer {{ flex: 1; }}
  .nav-meta {{
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 12px;
    color: var(--gf-text-secondary);
    font-variant-numeric: tabular-nums;
  }}
  .nav-meta b {{ color: var(--gf-text-primary); font-weight: 500; }}

  /* ----- Dashboard toolbar (Grafana dash controls) ----- */
  .dash-toolbar {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px;
    background: var(--gf-page-bg);
    border-bottom: 1px solid var(--gf-border-weak);
  }}
  .dash-title-wrap {{
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    padding-left: 4px;
  }}
  .dash-title {{
    margin: 0;
    font-size: 20px;
    font-weight: 500;
    color: var(--gf-text-max);
    letter-spacing: 0;
    line-height: 1.2;
  }}
  .dash-subtitle {{
    font-size: 12px;
    color: var(--gf-text-secondary);
  }}
  .dash-controls {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }}
  .gf-btn {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding: 0 10px;
    border-radius: 2px;
    border: 1px solid var(--gf-border-medium);
    background: var(--gf-primary-bg);
    color: var(--gf-text-primary);
    font-family: var(--gf-font);
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    appearance: none;
    -webkit-appearance: none;
  }}
  .gf-btn:hover {{
    border-color: var(--gf-action);
  }}
  .gf-btn.primary {{
    background: var(--gf-action);
    border-color: var(--gf-action);
    color: #fff;
  }}
  .gf-btn .ico {{
    opacity: 0.85;
    font-size: 14px;
    line-height: 1;
  }}
  .time-picker {{
    font-family: var(--gf-mono);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }}

  /* ----- Dashboard canvas ----- */
  .dashboard {{
    flex: 1;
    padding: 8px;
    background: var(--gf-page-bg);
  }}
  .row {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 8px;
    margin-bottom: 8px;
  }}
  .row-wide {{ display: block; }}
  .filter-bar {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    margin-bottom: 8px;
  }}
  .chip-filter {{
    cursor: pointer;
    background: var(--gf-primary-bg);
    border: 1px solid var(--gf-border-weak);
    color: var(--gf-text-secondary);
    border-radius: 2px;
    padding: 3px 8px;
    font-size: 11px;
    text-transform: lowercase;
  }}
  .chip-filter.active {{
    border-color: var(--gf-action);
    color: var(--gf-text-max);
  }}
  .filter-count {{
    margin-left: auto;
    font-size: 11px;
    color: var(--gf-text-disabled);
    font-variant-numeric: tabular-nums;
  }}
  .search-box {{
    height: 32px;
    min-width: 160px;
    border: 1px solid var(--gf-border-medium);
    border-radius: 2px;
    background: var(--gf-primary-bg);
    color: var(--gf-text-primary);
    padding: 0 10px;
    font-size: 12px;
    font-family: var(--gf-font);
  }}
  .panel.is-hidden {{ display: none !important; }}
  @media (max-width: 700px) {{
    .sidemenu {{ display: none; }}
    .search-box {{ min-width: 120px; }}
  }}

  /* ----- Panel chrome (core Grafana look) ----- */
  .panel {{
    background: var(--gf-panel-bg);
    border: 1px solid var(--gf-panel-border);
    border-radius: 2px;
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 220px;
    overflow: hidden;
  }}
  .panel-table {{
    min-height: 0;
    grid-column: 1 / -1;
    width: 100%;
  }}
  .row:has(.panel-table) {{
    display: block;
  }}

  .panel-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 28px;
    padding: 0 8px 0 8px;
    flex-shrink: 0;
  }}
  .panel-title {{
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    font-size: 12px;
    font-weight: 500;
    color: var(--gf-text-secondary);
  }}
  .panel-title-text {{
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--gf-text-secondary);
  }}
  .panel-desc {{
    color: var(--gf-text-disabled);
    font-size: 11px;
    font-weight: 400;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin-left: 4px;
  }}
  .series-dot {{
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }}
  .panel-menu {{
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    gap: 2px;
    width: 20px;
    height: 20px;
    opacity: 0.45;
    flex-shrink: 0;
  }}
  .panel-menu span {{
    width: 3px;
    height: 3px;
    border-radius: 50%;
    background: var(--gf-text-secondary);
  }}
  .panel:hover .panel-menu {{ opacity: 0.85; }}

  .panel-content {{
    flex: 1;
    padding: 0 8px 8px;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }}

  /* ----- Stat visualization ----- */
  .stat-content {{
    padding-top: 4px;
  }}
  .stat-value-wrap {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 8px 8px 0;
  }}
  .stat-value {{
    font-family: var(--gf-mono);
    font-size: 48px;
    font-weight: 500;
    line-height: 1.05;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }}
  .stat-title {{
    margin-top: 2px;
    font-size: 13px;
    color: var(--gf-text-secondary);
    font-weight: 400;
  }}
  .stat-used {{
    margin-top: 4px;
    font-size: 12px;
    color: var(--gf-text-disabled);
    font-variant-numeric: tabular-nums;
  }}
  .stat-reset {{
    margin-top: 4px;
    font-size: 12px;
    color: var(--gf-text-disabled);
    font-variant-numeric: tabular-nums;
    font-family: var(--gf-mono);
  }}
  .stat-reset b {{
    color: var(--gf-text-secondary);
    font-weight: 500;
  }}
  .stat-graph {{
    flex: 1;
    min-height: 56px;
    margin-top: 10px;
    position: relative;
  }}
  .stat-graph .spark {{
    width: 100%;
    height: 56px;
    display: block;
  }}
  .stat-extras {{
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid var(--gf-border-weak);
  }}
  .extra-row {{
    display: grid;
    grid-template-columns: 72px 72px 1fr;
    gap: 8px;
    font-size: 11px;
    padding: 3px 0;
    color: var(--gf-text-disabled);
    font-variant-numeric: tabular-nums;
  }}
  .extra-period {{ color: var(--gf-text-secondary); text-transform: lowercase; }}
  .extra-rem {{ font-family: var(--gf-mono); font-weight: 500; }}
  .extra-reset {{ text-align: right; font-family: var(--gf-mono); }}

  /* ----- Table panel ----- */
  .table-content {{
    padding: 0 0 4px;
    overflow-x: auto;
  }}
  .gf-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  .gf-table th {{
    text-align: left;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
    color: var(--gf-text-secondary);
    border-bottom: 1px solid var(--gf-border-weak);
    background: transparent;
    white-space: nowrap;
  }}
  .gf-table td {{
    padding: 8px 12px;
    border-bottom: 1px solid rgba(44, 50, 53, 0.55);
    vertical-align: middle;
  }}
  .gf-table tr:last-child td {{ border-bottom: 0; }}
  .gf-table tr:hover td {{ background: rgba(34, 37, 43, 0.55); }}
  .gf-table .mono {{
    font-family: var(--gf-mono);
    font-size: 12px;
    color: var(--gf-error);
  }}
  .gf-table .weak {{
    color: var(--gf-text-disabled);
    font-size: 12px;
  }}
  .gf-table .series-dot {{
    display: inline-block;
    margin-right: 8px;
    vertical-align: middle;
  }}
  .empty {{
    padding: 40px;
    text-align: center;
    color: var(--gf-text-disabled);
  }}

  .page-footer {{
    padding: 4px 12px 16px;
    font-size: 11px;
    color: var(--gf-text-disabled);
    line-height: 1.5;
  }}
  .page-footer code {{
    font-family: var(--gf-mono);
    font-size: 11px;
    background: var(--gf-primary-bg);
    border: 1px solid var(--gf-border-weak);
    border-radius: 2px;
    padding: 1px 6px;
  }}
</style>
</head>
<body>
  <div class="app">
    <nav class="sidemenu" aria-label="sidemenu">
      <div class="side-logo" title="Grafana-style"></div>
      <div class="side-icon active" title="Dashboards">Dash</div>
      <div class="side-icon" title="Explore">Exp</div>
      <div class="side-icon" title="Alerting">Alrt</div>
      <div style="flex:1"></div>
      <div class="side-icon" title="Admin">Adm</div>
    </nav>

    <div class="main">
      <header class="navbar">
        <div class="nav-breadcrumb">
          <span>Dashboards</span>
          <span class="sep">/</span>
          <span class="current">{_esc(title)}</span>
        </div>
        <div class="nav-spacer"></div>
        <div class="nav-meta">
          <span>live <b>{live_n}/{total}</b></span>
          <span>query <b>{wall_ms/1000:.1f}s</b></span>
        </div>
      </header>

      <div class="dash-toolbar">
        <div class="dash-title-wrap">
          <h1 class="dash-title">{_esc(title)}</h1>
          <div class="dash-subtitle">Claude · Codex · Grok — subscription remaining only</div>
        </div>
        <div class="dash-controls">
          <input type="search" id="profileSearch" class="search-box" placeholder="Filter profiles…" />
          <button type="button" class="gf-btn" id="themeToggle" title="Toggle light / dark">
            <span class="ico" id="themeIcon">◐</span>
            <span id="themeLabel">Theme</span>
          </button>
          <div class="gf-btn time-picker" title="Snapshot time">
            <span class="ico">⏱</span>
            {_esc(now)}
          </div>
          {f'<span class="gf-btn"><span class="live-dot"></span>Live · {int(poll_seconds)}s</span>' if live else '<span class="gf-btn">Snapshot</span>'}
        </div>
      </div>

      <div class="dashboard">
        <div class="filter-bar">
          <button type="button" class="chip chip-filter active" data-family="*">all</button>
          {family_chips}
          <span class="filter-count" id="filterCount">{len(live_cards)} live · {len(offline)} offline · {total} total</span>
        </div>
        {alert_html}
        <div class="row" id="liveGrid">
          {''.join(stat_panels)}
        </div>
        {table_panel}
      </div>

      <div class="page-footer">
        Static Grafana-style snapshot (no Grafana server). Refresh data:
        <code>python D:\\Panel\\limits.py --html --open</code>
      </div>
    </div>
  </div>
  <script type="application/json" id="snapshot">{data_json}</script>
  <script>
  (function () {{
    var KEY = "subscription-usage-panel-theme";
    var LIVE = {str(live).lower()};
    var POLL = {int(poll_seconds)};
    var root = document.documentElement;
    var btn = document.getElementById("themeToggle");
    var label = document.getElementById("themeLabel");
    var icon = document.getElementById("themeIcon");
    function apply(theme) {{
      theme = theme === "light" ? "light" : "dark";
      root.setAttribute("data-theme", theme);
      try {{ localStorage.setItem(KEY, theme); }} catch (e) {{}}
      if (label) label.textContent = theme === "dark" ? "Dark" : "Light";
      if (icon) icon.textContent = theme === "dark" ? "☾" : "☀";
    }}
    var saved = null;
    try {{ saved = localStorage.getItem(KEY); }} catch (e) {{}}
    apply(saved || root.getAttribute("data-theme") || "dark");
    if (btn) {{
      btn.addEventListener("click", function () {{
        var cur = root.getAttribute("data-theme") === "light" ? "light" : "dark";
        apply(cur === "dark" ? "light" : "dark");
      }});
    }}
    // Live mode: reload page on interval (server re-renders HTML with fresh data)
    if (LIVE && POLL > 0) {{
      setInterval(function () {{
        var t = root.getAttribute("data-theme") || "dark";
        var u = new URL(window.location.href);
        u.searchParams.set("theme", t);
        u.searchParams.set("_", String(Date.now()));
        window.location.replace(u.toString());
      }}, POLL * 1000);
    }}

    // Scale UI: filter by family + search (works with 100+ profiles)
    var activeFamily = "*";
    var searchBox = document.getElementById("profileSearch");
    var chips = document.querySelectorAll(".chip-filter");
    function applyFilters() {{
      var q = (searchBox && searchBox.value || "").toLowerCase().trim();
      var panels = document.querySelectorAll(".panel-stat");
      var shown = 0;
      panels.forEach(function (el) {{
        var fam = el.getAttribute("data-family") || "";
        var lab = el.getAttribute("data-label") || "";
        var okFam = activeFamily === "*" || fam === activeFamily;
        var okQ = !q || lab.indexOf(q) !== -1 || fam.indexOf(q) !== -1;
        var hide = !(okFam && okQ);
        el.classList.toggle("is-hidden", hide);
        if (!hide) shown += 1;
      }});
      var off = document.getElementById("offlinePanel");
      if (off) {{
        var offHide = activeFamily !== "*" && true;
        // keep offline visible unless searching for something else
        if (q) {{
          off.classList.toggle("is-hidden", true);
        }} else if (activeFamily !== "*") {{
          // show offline table only when "all"
          off.classList.toggle("is-hidden", true);
        }} else {{
          off.classList.toggle("is-hidden", false);
        }}
      }}
      var fc = document.getElementById("filterCount");
      if (fc) fc.textContent = shown + " shown · filter=" + activeFamily + (q ? (" · q=" + q) : "");
    }}
    chips.forEach(function (ch) {{
      ch.addEventListener("click", function () {{
        chips.forEach(function (c) {{ c.classList.remove("active"); }});
        ch.classList.add("active");
        activeFamily = ch.getAttribute("data-family") || "*";
        applyFilters();
      }});
    }});
    if (searchBox) searchBox.addEventListener("input", applyFilters);

    var tog = document.getElementById("toggleOffline");
    var offBody = document.getElementById("offlineBody");
    if (tog && offBody) {{
      // collapse offline by default when many rows
      var rows = offBody.querySelectorAll("tbody tr").length;
      if (rows > 8) {{
        offBody.style.display = "none";
        tog.textContent = "Expand";
      }}
      tog.addEventListener("click", function () {{
        var hid = offBody.style.display === "none";
        offBody.style.display = hid ? "" : "none";
        tog.textContent = hid ? "Collapse" : "Expand";
      }});
    }}
  }})();
  </script>
</body>
</html>
"""


def write_dashboard(
    results: List[ProfileResult],
    wall_ms: float,
    path,
    theme: str = "dark",
) -> None:
    path.write_text(
        render_dashboard_html(results, wall_ms, theme=theme, live=False),
        encoding="utf-8",
    )
