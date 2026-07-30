#!/usr/bin/env python3
"""Subscription Usage Panel — multi-profile remaining limits.

Usage:
  python limits.py
  python limits.py --html --open
  python limits.py --serve --open
  python limits.py --json
  python limits.py --list-profiles
  python limits.py --watch
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from panel.config import load_config
from panel.fetch import fetch_all
from panel.history import append_snapshot, attach_history
from panel.html_dash import write_dashboard
from panel.render import render_frame
from panel.schema import build_payload, exit_code_from_payload

DEFAULT_HTML = ROOT / "dashboard.html"


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Multi-profile subscription remaining limits (Claude/Codex/Grok+)"
    )
    p.add_argument("--watch", "-w", action="store_true", help="terminal auto-refresh")
    p.add_argument("--json", action="store_true", help="JSON stdout (schema sup.v1)")
    p.add_argument(
        "--html",
        nargs="?",
        const=str(DEFAULT_HTML),
        default=None,
        help=f"write HTML snapshot (default: {DEFAULT_HTML})",
    )
    p.add_argument(
        "--serve",
        action="store_true",
        help="live local server (HTML + /api/usage auto-refresh)",
    )
    p.add_argument("--host", default="127.0.0.1", help="serve host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765, help="serve port (default 8765)")
    p.add_argument("--open", action="store_true", help="open browser")
    p.add_argument("--theme", choices=("dark", "light"), default=None)
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--interval", type=int, default=None, help="refresh seconds (min 15)")
    p.add_argument("--all", "-a", action="store_true", help="show offline in terminal")
    p.add_argument("--list-profiles", action="store_true")
    p.add_argument(
        "--strict-exit",
        action="store_true",
        help="exit 1=warn 2=critical 3=no live (for CI/hooks)",
    )
    p.add_argument(
        "--family",
        action="append",
        default=None,
        help="only these families (repeatable), e.g. --family codex --family grok",
    )
    p.add_argument(
        "--profile",
        action="append",
        default=None,
        help="only these profile ids/labels (repeatable)",
    )
    p.add_argument(
        "--only-live",
        action="store_true",
        help="hide offline/auth profiles in terminal/HTML snapshot",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="parallel fetch workers (default 16, max 64)",
    )
    return p.parse_args(argv)


def run_watch(cfg, show_dead: bool) -> int:
    interval = cfg.interval
    show = show_dead
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    try:
        while True:
            results, wall = fetch_all(cfg)
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(
                render_frame(results, cfg, wall, show_dead=show, watch=True)
            )
            sys.stdout.flush()
            deadline = time.time() + interval
            while time.time() < deadline:
                key = _read_key_nonblocking()
                if key in ("\x03",):
                    raise KeyboardInterrupt
                if key in ("o", "O", "\x0f"):
                    break
                if key in ("d", "D"):
                    show = not show
                    break
                if key in ("q", "Q"):
                    return 0
                time.sleep(0.1)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()
    return 0


def _read_key_nonblocking() -> str | None:
    if os.name == "nt":
        try:
            import msvcrt

            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    msvcrt.getwch()
                    return None
                return ch
        except Exception:
            return None
        return None
    try:
        import select

        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
    except Exception:
        pass
    return None


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    _enable_windows_ansi()

    args = parse_args(argv)
    cfg = load_config(args.config)
    if args.interval is not None:
        cfg.interval = max(15, args.interval)
    if args.theme:
        cfg.theme = args.theme
    if args.workers is not None:
        cfg.workers = max(1, min(64, args.workers))
    if args.family:
        cfg.families_filter = [f.lower() for f in args.family]
        from panel.config import _apply_filters

        # re-filter from full discover
        cfg2 = load_config(args.config)
        cfg.profiles = cfg2.profiles
        cfg.families_filter = [f.lower() for f in args.family]
        if args.profile:
            cfg.profiles_filter = list(args.profile)
        _apply_filters(cfg)
    elif args.profile:
        cfg.profiles_filter = list(args.profile)
        from panel.config import _apply_filters

        cfg2 = load_config(args.config)
        cfg.profiles = cfg2.profiles
        cfg.profiles_filter = list(args.profile)
        _apply_filters(cfg)
    if args.only_live:
        cfg.only_live = True
        cfg.show_dead = False
    show_dead = bool(args.all or cfg.show_dead) and not cfg.only_live

    if args.list_profiles:
        fams = sorted({p.family for p in cfg.profiles})
        for p in cfg.profiles:
            flag = "on " if p.enabled else "off"
            print(f"{flag}  {p.id:28}  {p.family:12}  {p.label:24}  {p.home}")
        print(
            f"total={len(cfg.profiles)}  families={len(fams)}  "
            f"auto_discover={cfg.auto_discover}  workers={cfg.workers}"
        )
        print(f"families: {', '.join(fams)}")
        return 0

    if args.serve:
        from panel.server import serve

        serve(cfg, host=args.host, port=args.port, open_browser=args.open)
        return 0

    if args.watch:
        return run_watch(cfg, show_dead=show_dead)

    results, wall = fetch_all(cfg)
    payload = build_payload(
        results, wall, meta={"mode": "cli", "auto_discover": cfg.auto_discover}
    )
    append_snapshot(payload.get("profiles") or [])
    attach_history(payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.html:
        # optional only-live for snapshot cards
        if cfg.only_live:
            from panel.models import Status

            results = [r for r in results if r.status.value == "live"]
            payload = build_payload(results, wall, meta=payload.get("meta") or {})
        out = Path(args.html)
        write_dashboard(results, wall, out, theme=cfg.theme)
        print(
            f"Wrote {out.resolve()}  (profiles={len(results)}, "
            f"theme={cfg.theme}, workers={cfg.workers})"
        )
        if args.open:
            webbrowser.open(out.resolve().as_uri())
    else:
        s = payload.get("summary") or {}
        t = s.get("tightest")
        if t:
            print(
                f"Tightest: {t['label']}  rem {t['remaining_pct']}%  "
                f"({t.get('period')})  urgency={t.get('urgency')}"
            )
        for a in (payload.get("alerts") or [])[:5]:
            if a.get("level") in ("critical", "warn"):
                print(f"[{a['level'].upper()}] {a.get('message')}")
        sys.stdout.write(
            render_frame(results, cfg, wall, show_dead=show_dead, watch=False)
        )
        sys.stdout.flush()

    if args.strict_exit:
        return exit_code_from_payload(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
