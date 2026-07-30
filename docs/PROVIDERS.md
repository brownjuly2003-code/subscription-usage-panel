# Providers

## Contract

Each provider implements:

```python
def fetch_*(
    profile_id: str,
    label: str,
    home: Path,
    client: httpx.Client,
    timeout: float,
) -> ProfileResult:
    ...
```

Return `ProfileResult` with:

- `status`: `live` | `auth` | `dead` | `stale` | `error`
- `windows`: list of `Window(label, used_pct, rem_pct, reset, reset_at)`
- Never put secrets in `reason` / `meta`

Register:

```python
from panel.providers import register_provider
from panel.discover import register_family

register_family("myai", ".myai", "auth.json")
register_provider("myai", fetch_myai)
```

## Built-in

### Claude

- Home: `~/.claude`, `~/.claude-*`
- Token: `.credentials.json` → `claudeAiOauth.accessToken`
- API: `GET https://api.anthropic.com/api/oauth/usage`
- Windows: `five_hour`, `seven_day` utilization

### Codex

- Home: `~/.codex`, `~/.codex-*`
- Token: `auth.json` → `tokens.access_token` + `account_id`
- API: `GET https://chatgpt.com/backend-api/wham/usage`
- Windows: `rate_limit.primary_window` / `secondary_window`

### Grok (SuperGrok)

- Home: `~/.grok`, `~/.grok-*`
- Token: `auth.json` OIDC `key`
- API: gRPC-web `POST https://grok.com/grok_api_v2.GrokBuildBilling/GetGrokCreditsConfig`
- Metric: `credit_usage_percent` (subscription pool), **not** `cli-chat-proxy/v1/billing` absolute credits
