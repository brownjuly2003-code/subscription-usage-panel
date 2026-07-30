from __future__ import annotations

from datetime import datetime
from typing import Iterable, List

from panel.config import AppConfig
from panel.models import ProfileResult, Status, Window
from panel.timefmt import fmt_pct

RST = "\033[0m"
DIM = "\033[38;2;80;80;80m"
TITLE = "\033[1m"
SAGE = "\033[38;2;150;210;150m"
GOLD = "\033[38;2;215;195;125m"
ERR = "\033[38;2;225;150;150m"


def rgb(s: str) -> str:
    return f"\033[38;2;{s};1m" if s else TITLE


def pct_color(p: float) -> str:
    if p > 80:
        return ERR
    if p > 50:
        return GOLD
    return SAGE


def make_bar(pct: float, width: int) -> str:
    p = max(0.0, min(float(pct), 100.0))
    filled = int(p * width / 100.0)
    if pct > 0 and filled == 0:
        filled = 1
    if filled > width:
        filled = width
    empty = width - filled
    clr = pct_color(float(pct))
    return f"{clr}{'▰' * filled}{DIM}{'▱' * empty}{RST}"


def render_window(w: Window, bar_width: int) -> str:
    u = w.used_pct
    rem = w.rem_pct
    clr = pct_color(u)
    rem_clr = SAGE if rem > 20 else GOLD if rem > 0 else ERR
    parts = [
        f"{w.label:<3}",
        f"used {clr}{fmt_pct(u, 2)}{RST}",
        f"rem {rem_clr}{fmt_pct(rem, 2)}{RST}",
        make_bar(u, bar_width),
    ]
    if w.reset or w.reset_at:
        if w.reset_at and w.reset:
            parts.append(f"{DIM}· {w.reset_at} ({w.reset}){RST}")
        elif w.reset_at:
            parts.append(f"{DIM}· {w.reset_at}{RST}")
        else:
            parts.append(f"{DIM}· {w.reset}{RST}")
    return " ".join(parts)


def _display_windows(windows: List[Window]) -> List[Window]:
    """Drop unused secondary limit rows (e.g. Spark 0%) when primary exists."""
    if len(windows) <= 1:
        return list(windows)
    main = [
        w
        for w in windows
        if not (float(w.used_pct) <= 0.01 and float(w.rem_pct) >= 99.9)
    ]
    return main or list(windows)


def render_windows(windows: List[Window], bar_width: int) -> str:
    return "  ".join(
        render_window(w, bar_width) for w in _display_windows(windows)
    )


def filter_results(
    results: Iterable[ProfileResult], show_dead: bool
) -> list[ProfileResult]:
    if show_dead:
        return list(results)
    return [
        r
        for r in results
        if r.status in (Status.LIVE, Status.STALE)
        or (r.status == Status.AUTH and r.windows)
    ]


def render_frame(
    results: list[ProfileResult],
    cfg: AppConfig,
    wall_ms: float,
    show_dead: bool | None = None,
    watch: bool = False,
) -> str:
    if show_dead is None:
        show_dead = cfg.show_dead

    live_n = sum(1 for r in results if r.status == Status.LIVE)
    total = len(results)
    now = datetime.now().strftime("%H:%M:%S")
    lines: list[str] = []
    dead_note = "all profiles" if show_dead else "live/stale only"
    lines.append(
        f"{TITLE}Subscription usage{RST} {DIM}· {now} · live {live_n}/{total} · "
        f"{wall_ms/1000:.1f}s · {dead_note}{RST}"
    )

    visible = filter_results(results, show_dead=show_dead)
    hidden = [r for r in results if r not in visible]

    for r in visible:
        tclr = rgb(cfg.colors.get(r.family, ""))
        name = f"{tclr}{r.label:<16}{RST}"
        if r.windows and r.status in (Status.LIVE, Status.STALE):
            body = render_windows(r.windows, cfg.bar_width)
            tail = []
            if r.plan:
                tail.append(r.plan)
            if r.status == Status.STALE and r.reason:
                tail.append(r.reason)
            t = f" {DIM}{' · '.join(tail)}{RST}" if tail else ""
            lines.append(f"{name} {body}{t}")
        else:
            lines.append(f"{name} {ERR}{r.reason or r.status.value}{RST}")

    if not show_dead and hidden:
        lines.append(f"{DIM}— +{len(hidden)} dead/auth (--all) —{RST}")

    if watch:
        lines.append(f"{DIM}o refresh · d dead · q/Ctrl+C exit{RST}")
    return "\n".join(lines) + "\n"


def results_to_json(results: list[ProfileResult], wall_ms: float) -> dict:
    from panel.schema import build_payload

    return build_payload(results, wall_ms, meta={"mode": "cli"})
