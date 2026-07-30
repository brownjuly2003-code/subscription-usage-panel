# Research notes: path to 9.8/10

Date: 2026-07-30. Local only until quality bar met. Not published until checklist green.

## Competitors

| Tool | Strength | Gap we fill |
|------|----------|-------------|
| CodexBar | Many providers, macOS UI | Windows-first HTML, multi-home discover, serve mode |
| caut | Cross-platform CLI, 16 providers, robot JSON | Live browser dashboard, zero-Rust, subscription-only focus |
| ccusage | Claude cost blocks | Multi-network subscription remaining |
| ai-usage-monitor | Claude+Codex local API | More providers, discover, theme, history |

## What makes 9.8 (checklist)

Must-have (product):

1. Multi-profile auto-discover (done)
2. Subscription remaining only, no fake billing (done)
3. Absolute reset date once, no UI dupes (done)
4. Dark/light toggle (done)
5. **Live `--serve`** with auto-refresh HTML + JSON API
6. **Versioned JSON schema** for agents (`sup.v1`)
7. **Urgency ranking** + threshold alerts (warn/crit)
8. **Exit codes** for CI/hooks (0 ok, 1 warn, 2 crit, 3 auth/dead all)
9. **History** of remaining → real sparkline (not synthetic)
10. **Tests** with fixtures + GitHub Actions
11. **pyproject** install entrypoint
12. **Plugin path** for new families
13. At least **+1 provider** with local creds if reliable (Gemini/Kimi)

Nice (if time):

- Status page links per family
- Export markdown report

## Decision

Ship only when checklist 1–12 pass smoke + tests. Synthetic sparklines → replace with history-based or remove.
