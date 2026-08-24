#!/usr/bin/env python3
"""Compact Codex status line, Claude-Code style.

Reads Codex's own local state (~/.codex/state_5.sqlite) — no API calls, no tokens spent.

  python codex_status.py                 # line for the current directory's thread
  python codex_status.py --cwd ~/src/myapp # line for a specific project
  python codex_status.py --all           # every thread touched in the last 30 min
  python codex_status.py --watch 5       # refresh in place every 5s (use in a split pane)

Note: 5h/weekly rate limits are NOT stored on disk — Codex keeps them in-process only. Use the built-in [tui].status_line items five-hour-limit / weekly-limit
inside the Codex TUI for those.
"""
import argparse
import os
import sqlite3
import sys
import time

DB = os.path.expanduser("~/.codex/state_5.sqlite")
SEP = " \u00b7 "
SLASHES = chr(92)
UNC_PREFIX = chr(92) + chr(92) + "?" + chr(92)
C = {
    "model": "\033[38;5;110m", "path": "\033[38;5;150m", "branch": "\033[38;5;180m",
    "tok": "\033[38;5;146m", "age": "\033[38;5;245m", "dim": "\033[38;5;240m",
    "hot": "\033[38;5;209m", "off": "\033[0m",
}


def paint(key, text, color):
    return f"{C[key]}{text}{C['off']}" if color else text


def clean_cwd(cwd):
    if not cwd:
        return None
    return cwd.replace(UNC_PREFIX, '')


def project(cwd):
    cwd = clean_cwd(cwd) or ""
    name = os.path.basename(cwd.rstrip('/' + SLASHES))
    return name or cwd or "?"


def human_tokens(n):
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1000}k"
    return str(n)


def human_age(ms):
    s = max(0, (time.time() * 1000 - (ms or 0)) / 1000)
    if s < 90:
        return f"{s:.0f}s"
    if s < 5400:
        return f"{s / 60:.0f}m"
    if s < 172800:
        return f"{s / 3600:.0f}h"
    return f"{s / 86400:.0f}d"


def rows(limit=200):
    if not os.path.exists(DB):
        return []
    uri = "file:" + DB.replace(os.sep, "/") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=1.0)
    except sqlite3.Error:
        return []
    try:
        q = """select cwd, model, reasoning_effort, tokens_used, git_branch, source,
                      updated_at_ms, title
               from threads where archived = 0
               order by updated_at_ms desc limit ?"""
        return list(con.execute(q, (limit,)))
    except sqlite3.Error:
        return []
    finally:
        con.close()


def render(row, color=True, with_project=True):
    cwd, model, effort, tokens, branch, source, updated, _title = row
    parts = []
    if model:
        parts.append(paint("model", f"{model} {effort or ''}".strip(), color))
    if with_project:
        parts.append(paint("path", project(cwd), color))
    if branch:
        parts.append(paint("branch", branch, color))
    if tokens:
        parts.append(paint("tok", human_tokens(tokens), color))
    age = human_age(updated)
    key = "hot" if (time.time() * 1000 - (updated or 0)) < 120_000 else "age"
    parts.append(paint(key, age, color))
    if source and source != "cli":
        parts.append(paint("dim", source, color))
    return SEP.join(parts)


def pick(cwd_filter):
    """Newest thread for this project; None when the project has no Codex history."""
    target = os.path.abspath(cwd_filter).rstrip("/" + SLASHES).lower()
    for r in rows():
        if (clean_cwd(r[0]) or "").rstrip("/" + SLASHES).lower() == target:
            return r
    return None


def line(args):
    if args.all:
        cutoff = time.time() * 1000 - args.window * 60_000
        active = [r for r in rows() if (r[6] or 0) >= cutoff]
        if not active:
            return paint("dim", f"codex: тихо ({args.window}m)", not args.no_color)
        head = paint("dim", f"codex \u25cf {len(active)}", not args.no_color)
        return head + SEP + " \u2502 ".join(render(r, not args.no_color) for r in active[:6])
    row = pick(args.cwd)
    if not row:
        return paint("dim", f"codex: нет сессий — {project(args.cwd)}", not args.no_color)
    return render(row, not args.no_color, with_project=False)


def main():
    ap = argparse.ArgumentParser(description="Codex status line from local state")
    ap.add_argument("--cwd", default=None, help="project dir (default: current)")
    ap.add_argument("--all", action="store_true", help="all recently active threads")
    ap.add_argument("--window", type=int, default=30, help="--all window, minutes")
    ap.add_argument("--watch", type=int, metavar="SEC", help="refresh in place")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    if args.cwd is None and not args.all:
        args.cwd = os.getcwd()
    if not args.watch:
        print(line(args))
        return
    if os.name == "nt":
        os.system("")  # enable ANSI in legacy consoles
    try:
        while True:
            sys.stdout.write("\r\033[2K" + line(args))
            sys.stdout.flush()
            time.sleep(max(1, args.watch))
    except KeyboardInterrupt:
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
