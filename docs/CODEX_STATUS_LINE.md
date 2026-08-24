# Codex CLI status line

Quota lives in this panel. Everything *else* about a running Codex session — model, project, branch, context, run state — belongs in the terminal, and Codex has a configurable footer for it that is off by default.

```
gpt-5.5 xhigh · myapp · main · Context 42% used · 5h 17% · Weekly 62% · Ready
```

Codex has no `statusLine` command hook like Claude Code ([openai/codex#17827](https://github.com/openai/codex/issues/17827) is open; the PR that added one was closed). What exists is a fixed item picker — which is enough for most of what people ask that hook for.

## Turn it on

`$CODEX_HOME/config.toml` (default `~/.codex/config.toml`):

```toml
[tui]
status_line = [
  "model-with-reasoning",
  "project-name",
  "git-branch",
  "context-used",
  "five-hour-limit",
  "weekly-limit",
  "run-state",
  "task-progress",
]
status_line_use_colors = true

# Second surface: window/tab title — readable when the window is minimized.
terminal_title = ["activity", "project-name", "git-branch", "context-used"]
```

Array order is screen order. `/statusline` inside Codex is the same thing interactively, with live preview and arrow-key reordering.

## Item ids

Verified against `codex-rs/tui/src/bottom_pane/status_line_setup.rs` at tag `rust-v0.149.1`. Aliases in parentheses.

| Group | ids |
|---|---|
| Model | `model` (`model-name`), `model-with-reasoning`, `reasoning` |
| Location | `current-dir`, `project-name` (`project`, `project-root`) |
| Git | `git-branch`, `pull-request-number`, `branch-changes` |
| State | `run-state` (`status`), `permissions`, `approval-mode` (`approval`), `fast-mode`, `raw-output` |
| Context | `context-remaining`, `context-used` (`context-usage`), `context-window-size` |
| Tokens & cost | `used-tokens`, `total-input-tokens`, `total-output-tokens`, `thread-credits`, `estimated-thread-cost` |
| Limits | `five-hour-limit`, `weekly-limit` |
| Session | `thread-title`, `thread-id` (`session-id`), `workspace-headline`, `task-progress`, `codex-version` |

`terminal_title` takes the same ids plus `app-name` and `activity` (`spinner`), minus the git and permission ones.

## Gotchas

| Symptom | Cause |
|---|---|
| Config edited, footer unchanged | Multiple `CODEX_HOME`s. Each has its own `config.toml`, and account launchers copy the base one **once**. Edit every home you actually launch. |
| An item never shows up | Items with no data are hidden, not blanked. Rate limits arrive with the first API response; git items need a repo. |
| A typo silently does nothing | `--strict-config` does not validate status-line ids. Unknown ids are dropped at render time without an error. |
| Custom text won't render | The separator is hard-coded to `" · "`, and literal strings pass the TOML layer only to be discarded by the renderer. |

## `tools/codex_status.py`

The footer only exists inside the Codex TUI, for the one session in front of you. Sessions started by an editor or an agent have no footer at all.

The script reads Codex's own state database (`$CODEX_HOME/state_5.sqlite`, read-only) and prints one line. No API calls, no tokens, no credentials touched.

```console
$ python tools/codex_status.py --all
codex ● 3 · gpt-5.5 xhigh · myapp · main · 128k · 40s · vscode │ gpt-5.5 high · api · fix/retry · 45k · 3m │ gpt-5.5 xhigh · docs · main · 12k · 20m

$ python tools/codex_status.py
gpt-5.5 xhigh · main · 128k · 40s
```

| Flag | Meaning |
|---|---|
| *(none)* | the current directory's thread |
| `--cwd PATH` | a specific project |
| `--all` | every thread touched in the last 30 minutes |
| `--window N` | change that window, in minutes |
| `--watch N` | redraw in place every N seconds |
| `--no-color` | plain output for pipes and screen readers |

Python 3.8+, standard library only.

### As a bar

tmux:

```tmux
set -g status-interval 5
set -g status-right "#(python3 tools/codex_status.py --all --no-color) │ %H:%M"
```

zellij, via a [zjstatus](https://github.com/dj95/zjstatus) `command_` module:

```kdl
format_right "{command_codex} {datetime}"

command_codex_command  "python3 /path/to/tools/codex_status.py --all --no-color"
command_codex_interval "5"
```

Windows Terminal, as a thin pane along the bottom:

```powershell
wt -w 0 sp -H -s 0.08 powershell -NoLogo -NoProfile -Command "python tools\codex_status.py --all --watch 5"
```

## Why the script has no rate limits in it

They are not on disk. Codex keeps the 5h/weekly windows in process — they stopped appearing in the rollout JSONL in mid-2026 and were never written to the state database. Anything showing them offline is reading a stale cache.

Two honest sources exist, and this repo is one of them:

- **inside a session** — the built-in `five-hour-limit` / `weekly-limit` items, straight from the live response;
- **outside a session** — `panel/providers/codex.py`, which refreshes the OAuth token the same way the CLI does and reads the plan windows (see [PROVIDERS.md](PROVIDERS.md)).

Which is the split worth keeping: Codex-owned state in the Codex-rendered footer, quota in the panel, and the local state file for the one thing neither covers — what every *other* session is doing right now.
