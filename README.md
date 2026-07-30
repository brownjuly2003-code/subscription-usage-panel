# Subscription Usage Panel

Universal **multi-network × multi-profile** dashboard for **subscription / plan remaining limits**.

Designed for fleets like *20 provider families × 100 homes* — not a single-user hardcoded setup.

Not API cost noise. Not session token totals. **Remaining quota windows only.**

[![CI](https://github.com/brownjuly2003-code/subscription-usage-panel/actions/workflows/ci.yml/badge.svg)](https://github.com/brownjuly2003-code/subscription-usage-panel/actions/workflows/ci.yml)

## Design goals

| Goal | How |
|------|-----|
| Many networks | Declarative `panel/catalog.yaml` (19 families) + plugins |
| Many profiles | Auto-discover every matching home under `~` |
| Fast at scale | Parallel fetch (`workers: 16–64`) |
| Usable UI at 100 cards | Family chips, search box, collapsible offline table |
| Automation | JSON schema `sup.v1`, `--strict-exit`, live `--serve` |
| Themes | Dark / Light toggle |

## Install

```bash
git clone https://github.com/brownjuly2003-code/subscription-usage-panel.git
cd subscription-usage-panel
python -m venv .venv
pip install -r requirements.txt
```

## Quick start

```bash
python limits.py --list-profiles
python limits.py
python limits.py --html --open
python limits.py --serve --open          # live dashboard
python limits.py --json                  # schema sup.v1
python limits.py --strict-exit           # CI hooks
```

### Filters (for huge fleets)

```bash
python limits.py --family codex --family grok
python limits.py --profile codex-work --profile grok-personal
python limits.py --only-live
python limits.py --workers 32 --html --open
```

## Catalog of networks

Rules live in **`panel/catalog.yaml`** (extend without rewriting core code):

- **Implemented fetchers:** `claude`, `codex`, `grok`, `gemini`, `kimi`, `openrouter`, `openai`, `github`
- **Discoverable stubs** (home/env detected, remaining when you add a fetcher or token works later):  
  `cursor`, `copilot`, `amp`, `opencode`, `zai`, `minimax`, `windsurf`, `continue`, `aider`, `litellm`, `anthropic_api`

A user with no local Cursor/Gemini today still benefits: **tomorrow’s homes appear automatically**.

### Plugin

```python
from panel.providers import register_provider
from panel.discover import register_family

register_family("myai", ".myai", "auth.json")
register_provider("myai", fetch_myai)
```

Or add a family block to `catalog.yaml` + implement `fetch_*`.

See [docs/PROVIDERS.md](docs/PROVIDERS.md).

## Multi-profile discovery

For each catalog family, scans:

- `~/{prefix}`, `~/{prefix}-*`, `~/{prefix}_*`
- nested prefixes like `~/.config/github-copilot`
- env keys (`OPENROUTER_API_KEY`, `GH_TOKEN`, …) → virtual `FAMILY/env` profile
- skips `*archive*`, `*backup*`, …

## Dashboard UX (scale)

- Auto-fill grid of stat panels (one profile = one card)
- **Family filter chips** + **search**
- Offline table **collapsed** when many rows
- Dark / Light theme
- Alerts strip (critical / warn)
- Absolute **reset date once** + relative once
- History-based sparkline when `.cache/history` has points; otherwise honest bar

### Live server

```bash
python limits.py --serve --open --port 8765 --workers 32
```

| URL | |
|-----|--|
| `/` | Live HTML (auto-refresh) |
| `/api/usage` | `sup.v1` JSON |
| `/api/refresh` | Force re-fetch |
| `/api/health` | Health |

## Config

Copy `config.example.yaml` → `config.yaml` (gitignored).

```yaml
auto_discover: true
workers: 32
theme: dark
# families: [claude, codex, grok]
# only_live: true
```

## Exit codes (`--strict-exit`)

| Code | |
|------|--|
| 0 | OK |
| 1 | remaining ≤ 20% |
| 2 | remaining ≤ 10% |
| 3 | no live profiles |

## Security

- Uses credentials already stored by official CLIs / env
- Never prints secrets
- `config.yaml`, `dashboard.html`, `.cache/` gitignored
- Serve defaults to `127.0.0.1`

## Tests

```bash
pip install pytest
pytest -q
```

## License

MIT

## Disclaimer

Unofficial. Not affiliated with Anthropic, OpenAI, xAI, Google, etc. Undocumented APIs change.
