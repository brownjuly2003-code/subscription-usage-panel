# Providers

Built-in families (register more via `register_provider` / `register_family`):

| Family | Discover homes | Auth | Metric |
|--------|----------------|------|--------|
| **claude** | `~/.claude*` | OAuth `.credentials.json` | 5h / 7d utilization |
| **codex** | `~/.codex*` | ChatGPT `auth.json` | plan rate windows |
| **grok** | `~/.grok*` | OIDC `auth.json` | SuperGrok pool % |
| **gemini** | `~/.gemini*` | OAuth file or `GEMINI_API_KEY` | best-effort quota / auth |
| **kimi** | `~/.kimi*`, `~/.kimi-code` | token file or `KIMI_API_KEY` | 5h / 7d / mo windows |
| **openrouter** | `~/.openrouter*` | `OPENROUTER_API_KEY` | key limit remaining |
| **openai** | `~/.openai*` | `OPENAI_API_KEY` | key valid (plan → codex) |
| **github** | env / `gh` hosts | `GH_TOKEN` | REST rate limit remaining |

## Notes

- **GitHub** = API rate limit, **not** Copilot premium quota (undocumented).
- **OpenAI API key** ≠ ChatGPT subscription; use **codex** profiles for Plus/Pro windows.
- **Gemini API key** rarely exposes remaining %; OAuth path is preferred when available.
- Env-only keys create a virtual `FAMILY/env` profile when no home is found.

## Silent token refresh

Short-lived access tokens expire independently of the subscription pool. Claude Code / Codex / Grok CLI silent-refresh via stored refresh tokens; the panel does the same before billing probes so idle homes do not look “dead” until the next interactive CLI run.

| Family | Token store | Refresh endpoint |
|--------|-------------|------------------|
| **claude** | `~/.claude*/.credentials.json` → `claudeAiOauth` | `console.anthropic.com/v1/oauth/token` |
| **codex** | `~/.codex*/auth.json` → `tokens` | `auth.openai.com/oauth/token` |
| **grok** | `~/.grok*/auth.json` → OIDC entry | `{issuer}/oauth2/token` (default `auth.x.ai`) |

Refresh rotates `refresh_token` when the IdP returns a new one; the panel writes it back atomically (`.panel-tmp` → replace). If refresh fails (`invalid_grant` / revoked), status stays AUTH/DEAD until `claude login` / `codex login` / `grok login`.

**Grok race safety:** rotating refresh tokens + concurrent panel/CLI refresh used to burn sessions (`Refresh token has been revoked`). The panel now takes the same advisory `auth.json.lock` (`{pid}:{unix_ts}`) as Grok CLI, re-reads under the lock, and on `invalid_grant` accepts a peer-written fresh JWT. Last good SuperGrok pool is cached in `~/.grok*/.panel-grok-usage.json` so a dead RT shows **STALE** numbers instead of a blank card until you re-login once.

**Not refreshed (by design):** API keys (OpenRouter, OpenAI key, Gemini key, Kimi key, `GH_TOKEN`) — they do not use this OIDC path. Gemini OAuth has no silent refresh here yet (re-login via Gemini CLI).

## Contract

```python
def fetch_*(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult: ...
```

```python
from panel.providers import register_provider
from panel.discover import register_family

register_family("myai", ".myai", "auth.json")
register_provider("myai", fetch_myai)
```
