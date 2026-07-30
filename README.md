# Subscription Usage Panel

Local multi-profile dashboard for **subscription remaining limits** (not API billing cost, not session token totals).

Built-in providers:

| Family | Source | What you see |
|--------|--------|----------------|
| **Claude** | `api.anthropic.com/api/oauth/usage` | 5h / 7d utilization |
| **Codex** | `chatgpt.com/backend-api/wham/usage` | plan rate windows |
| **Grok** | `GetGrokCreditsConfig` (gRPC-web) | SuperGrok pool % |

Grafana-inspired HTML (static snapshot) with **dark / light** theme toggle. Terminal mode included.

> Unofficial. Uses local CLI credentials already on your machine. No passwords are stored by this tool.

## Why

You run several AI CLIs with **several accounts/homes**. Official UIs are scattered. This tool:

1. **Auto-discovers** profile homes under `~` (e.g. `~/.claude-work`, `~/.codex-personal`, `~/.grok`)
2. Fetches **subscription usage only**
3. Renders a clean remaining-focused dashboard you can open in any browser

## Install

```bash
git clone https://github.com/brownjuly2003-code/subscription-usage-panel.git
cd subscription-usage-panel
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -r requirements.txt
```

Optional: copy `config.example.yaml` → `config.yaml` (gitignored).

## Usage

```bash
# list discovered profiles
python limits.py --list-profiles

# terminal
python limits.py

# Grafana-style HTML + open browser
python limits.py --html --open

# light default theme (toggle still works in the page)
python limits.py --html --theme light --open

# machine-readable
python limits.py --json
```

Windows helper:

```powershell
.\open-dashboard.ps1
```

### HTML theme

- Button **Dark / Light** in the toolbar
- Choice stored in `localStorage` (`subscription-usage-panel-theme`)
- Default from `theme:` in config or `--theme`

## Profiles & multi-network

### Auto-discover (default)

Scans `$HOME` for:

| Family | Home pattern | Credential file |
|--------|--------------|-----------------|
| claude | `.claude`, `.claude-*` | `.credentials.json` |
| codex | `.codex`, `.codex-*` | `auth.json` |
| grok | `.grok`, `.grok-*` | `auth.json` |

Archive-like names (`*cold_archive*`, `*backup*`, …) are skipped.

### Explicit config

```yaml
auto_discover: true
profiles:
  - id: codex-work
    family: codex
    label: CODEX/work
    home: ~/.codex-work
    enabled: true
```

Explicit entries override discovery for the same home path.

### Add another network (fork / plugin)

```python
# my_provider.py
from panel.providers import register_provider
from panel.discover import register_family

def fetch_my(...):
    ...

register_family("myai", ".myai", "auth.json")
register_provider("myai", fetch_my)
```

Then set `family: myai` in config, or rely on discovery once the home layout matches.

## Security

- Reads local auth files written by official CLIs (`claude`, `codex`, `grok login`)
- Never prints access tokens
- `config.yaml` and `dashboard.html` are gitignored (local only)
- Do not commit real credentials

## Architecture

```
limits.py              CLI
panel/
  config.py            YAML + merge discover
  discover.py          multi-home scan
  fetch.py             parallel httpx
  html_dash.py         Grafana-inspired HTML
  render.py            terminal
  providers/
    claude.py
    codex.py
    grok.py
```

Grok path follows the approach documented by [CodexBar](https://github.com/steipete/CodexBar/blob/main/docs/grok.md) (`GetGrokCreditsConfig`), not the misleading monthly API credit counter.

## Requirements

- Python 3.10+
- `httpx`, `PyYAML`
- Local authenticated CLIs for the providers you enable

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

Not affiliated with Anthropic, OpenAI, or xAI. APIs and file layouts can change; treat this as a best-effort local helper.
