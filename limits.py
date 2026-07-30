#!/usr/bin/env python3
"""Subscription usage panel — Claude / Codex / Grok multi-profile.

Usage:
  python limits.py              # terminal
  python limits.py --html       # write dashboard.html
  python limits.py --html --open
  python limits.py --json
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
from panel.html_dash import write_dashboard
from panel.render import render_frame, results_to_json

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
    p = argparse.ArgumentParser(description="Subscription remaining limits panel")
    p.add_argument("--watch", "-w", action="store_true", help="terminal auto-refresh")
    p.add_argument("--once", action="store_true", help="single shot (default)")
    p.add_argument("--all", "-a", action="store_true", help="include dead/auth")
    p.add_argument("--json", action="store_true", help="JSON stdout")
    p.add_argument(
        "--html",
        nargs="?",
        const=str(DEFAULT_HTML),
        default=None,
        help=f"write Grafana-style HTML (default: {DEFAULT_HTML})",
    )
    p.add_argument(
        "--open",
        action="store_true",
        help="open HTML in browser after --html",
    )
    p.add_argument(
        "--theme",
        choices=("dark", "light"),
        default=None,
        help="default HTML theme (also toggleable in the page)",
    )
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--interval", type=int, default=None)
    p.add_argument(
        "--list-profiles",
        action="store_true",
        help="list discovered/configured profiles and exit",
    )
    return p.parse_args(argv)


def run_once(cfg, show_dead: bool, as_json: bool, html_path: str | None, do_open: bool) -> int:
    results, wall = fetch_all(cfg)
    if as_json:
        print(json.dumps(results_to_json(results, wall), ensure_ascii=False, indent=2))
    elif html_path:
        out = Path(html_path)
        write_dashboard(results, wall, out, theme=getattr(cfg, "theme", "dark"))
        print(f"Wrote {out.resolve()}  (profiles={len(results)}, theme={cfg.theme})")
        if do_open:
            webbrowser.open(out.resolve().as_uri())
    else:
        sys.stdout.write(
            render_frame(results, cfg, wall, show_dead=show_dead, watch=False)
        )
        sys.stdout.flush()
    return 0


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
    show_dead = bool(args.all or cfg.show_dead)

    if args.list_profiles:
        for p in cfg.profiles:
            flag = "on " if p.enabled else "off"
            print(f"{flag}  {p.id:24}  {p.family:8}  {p.label:20}  {p.home}")
        print(f"total={len(cfg.profiles)}  auto_discover={cfg.auto_discover}")
        return 0

    if args.watch:
        return run_watch(cfg, show_dead=show_dead)
    return run_once(
        cfg,
        show_dead=show_dead,
        as_json=args.json,
        html_path=args.html,
        do_open=args.open,
    )


if __name__ == "__main__":
    raise SystemExit(main())
