# Subscription Usage Panel

**Local multi-profile dashboard for subscription remaining limits** across popular AI coding providers.

Not API billing noise. Not session token cost. **Plan / quota remaining only.**

### Built-in families

| Family | Discover / env | Metric |
|--------|----------------|--------|
| Claude | `~/.claude*` | 5h / 7d utilization |
| Codex | `~/.codex*` | ChatGPT plan windows |
| Grok | `~/.grok*` | SuperGrok pool % |
| Gemini | `~/.gemini*`, `GEMINI_API_KEY` | OAuth quota / key |
| Kimi | `~/.kimi*`, `KIMI_API_KEY` | coding usage windows |
| OpenRouter | `OPENROUTER_API_KEY` | key limit remaining |
| OpenAI | `OPENAI_API_KEY` | key valid (plan → codex) |
| GitHub | `GH_TOKEN` / `gh` | REST rate limit remaining |

More via plugins: `register_provider` / `register_family`.

[![CI](https://github.com/brownjuly2003-code/subscription-usage-panel/actions/workflows/ci.yml/badge.svg)](https://github.com/brownjuly2003-code/subscription-usage-panel/actions/workflows/ci.yml)

## Why this exists

You juggle **multiple AI CLIs** and **multiple homes** (`~/.codex-work`, `~/.claude`, `~/.grok-…`).  
Official UIs are scattered. This tool:

1. **Auto-discovers** every profile home under `~`
2. Fetches **subscription remaining** in parallel
3. Surfaces **alerts** (critical / warn) + **absolute reset dates**
4. Serves a **live Grafana-inspired dashboard** (`--serve`) or a static HTML snapshot
5. Speaks **versioned JSON (`sup.v1`)** for agents and CI hooks

## Install

```bash
git clone https://github.com/brownjuly2003-code/subscription-usage-panel.git
cd subscription-usage-panel
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
# optional editable: pip install -e ".[dev]"
```

## Quick start

```bash
python limits.py --list-profiles   # what will be scanned
python limits.py                   # terminal + alerts
python limits.py --html --open     # static dashboard
python limits.py --serve --open    # LIVE dashboard (auto-refresh)
python limits.py --json            # schema sup.v1
python limits.py --strict-exit     # exit 1=warn 2=crit 3=no-live
```

Windows:

```powershell
.\open-dashboard.ps1
```

### Live server

```bash
python limits.py --serve --open --port 8765
```

| URL | Purpose |
|-----|---------|
| `http://127.0.0.1:8765/` | Live HTML (polls every `interval` s) |
| `/api/usage` | JSON `sup.v1` |
| `/api/refresh` | Force re-fetch |
| `/api/health` | Liveness |

Theme: **Dark / Light** toggle in the toolbar (persisted in `localStorage`).

## Multi-network & multi-profile

### Auto-discover (default)

| Family | Homes | Credential |
|--------|-------|------------|
| claude | `~/.claude`, `~/.claude-*` | `.credentials.json` |
| codex | `~/.codex`, `~/.codex-*` | `auth.json` |
| grok | `~/.grok`, `~/.grok-*` | `auth.json` |

Skip patterns: `*archive*`, `*backup*`, `*cold*`, …

### Explicit config

Copy `config.example.yaml` → `config.yaml` (gitignored):

```yaml
auto_discover: true
theme: dark
interval: 60
profiles:
  - id: codex-work
    family: codex
    label: CODEX/work
    home: ~/.codex-work
```

### Plugin / new family

```python
from panel.providers import register_provider
from panel.discover import register_family

register_family("myai", ".myai", "auth.json")
register_provider("myai", fetch_myai)
```

See [docs/PROVIDERS.md](docs/PROVIDERS.md).

## JSON schema (`sup.v1`)

```json
{
  "schemaVersion": "sup.v1",
  "summary": {
    "profiles_live": 3,
    "alerts_critical": 1,
    "tightest": { "label": "CODEX/work", "remaining_pct": 4.0, "period": "week" }
  },
  "alerts": [{ "level": "critical", "message": "..." }],
  "profiles": [{ "id": "...", "urgency": "critical", "primary": { "remaining_pct": 4.0, "reset_at": "..." } }]
}
```

### Exit codes (`--strict-exit`)

| Code | Meaning |
|------|---------|
| 0 | Live profiles OK |
| 1 | Remaining ≤ 20% (warn) |
| 2 | Remaining ≤ 10% (critical) |
| 3 | No live profiles |

## Data sources (subscription only)

| Family | Endpoint |
|--------|----------|
| Claude | `GET api.anthropic.com/api/oauth/usage` |
| Codex | `GET chatgpt.com/backend-api/wham/usage` |
| Grok | gRPC-web `GetGrokCreditsConfig` (pool %, not monthly API credit counters) |

History: local `.cache/history/*.jsonl` for **real** sparklines (no synthetic curves).

## Security

- Uses credentials already written by official CLIs
- Never prints tokens
- `config.yaml` / `dashboard.html` / `.cache/` gitignored
- Serve binds `127.0.0.1` by default

## Tests

```bash
pip install pytest
pytest -q
```

## Roadmap toward 10/10

- Optional Gemini / Cursor providers when stable local auth is available
- Webhook / desktop notify on critical
- Dashboard filters by family

## License

MIT — [LICENSE](LICENSE)

## Disclaimer

Unofficial. Not affiliated with Anthropic, OpenAI, or xAI. Undocumented APIs can change.
