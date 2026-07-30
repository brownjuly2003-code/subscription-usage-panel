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
