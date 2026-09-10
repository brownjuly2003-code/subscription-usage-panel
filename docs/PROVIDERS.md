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
| **zai** | `~/.zai*` | `ZAI_API_KEY` / home `api_key` | GLM Coding Plan 5h / 7d credits |

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

**Grok token ownership (important):** rotating `refresh_token` must have **one writer**.  
Panel used to OIDC-refresh itself and race the CLI → `Refresh token has been revoked` → blank/dead personal card.  

**Current rule:** if `~/.grok*/bin/grok.exe` exists, the **CLI owns `auth.json`**. Panel only *reads* the access JWT and, near expiry, runs `grok models` with `GROK_HOME` set to that home. Panel OIDC write is off unless `PANEL_GROK_OIDC_REFRESH=1`.

**Two homes, two logins:**  
| Home | Typical email | Who updates it |
|------|---------------|----------------|
| `~/.grok` | personal | only login with `GROK_HOME=%USERPROFILE%\.grok` |
| `~/.grok-work` | work | Grok Build / work CLI |

Logging in from Grok Build does **not** fix personal. Use `Heal-Grok-Personal.bat` once for `~/.grok`.

**If RT is already revoked:** ride access JWT → then **STALE** from `.panel-grok-usage.json` until a successful login into the **correct** home.

## Grok missing percent ≠ 0% used

`GetGrokCreditsConfig` **drops** `credit_usage_percent` on a spent pool while keeping the
same window bounds; the CLI then fails with `402 Grok Build usage balance exhausted`.
Observed on `~/.grok` 2026-09-09 05:17 local: the field went 100.0 → absent, bounds
unchanged at 03.09 → 10.09.

proto3 also omits a default `0.0`, so absence is genuinely ambiguous. The card shows
**remaining = 100 − used**, so reading absence as `0%` paints a green **100% left** —
the exact inverse of the truth, and only ever at the moment the quota dies.

**Rule:** substitute the proto3 default only when the account is still a paid
SuperGrok tier **and** `period_start`/`period_end` moved forward past the bounds
stored in `.panel-grok-usage.json`. Same window, or no stored window at all, means
no proof of a roll → **STALE** last known, never an invented pool.
Stale cards carry a `last known` chip so a cached number cannot pass as a live one.

**Ended SuperGrok ≠ full pool.** After the plan lapses, `GetGrokCreditsConfig` still
returns a weekly `currentPeriod` and still omits `credit_usage_percent` — the same
shape as a proto3 roll. Observed on `~/.grok` 2026-09-10: CLI
`subscriptionTier: Free`, JWT has no `tier` claim, REST `/v1/billing?format=credits`
has no percent; the card was green **100% SuperGrok**. Plan comes from
`GET /v1/settings` `subscription_tier_display` (fallback: JWT `tier`; OAuth Free
omits the claim). Free / non-SuperGrok → remaining **0%**, label **Free**, no reset
date, never SuperGrok 100%.

**Not refreshed (by design):** API keys (OpenRouter, OpenAI key, Gemini key, Kimi key, z.ai key, `GH_TOKEN`) — they do not use this OIDC path. Gemini OAuth has no silent refresh here yet (re-login via Gemini CLI).

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
