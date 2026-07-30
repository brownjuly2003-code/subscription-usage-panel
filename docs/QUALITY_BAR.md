# Quality bar (target 9.8/10)

## Research inputs

- CodexBar / caut: multi-provider, robot JSON, multi-account
- Our edge: Windows + multi-home discover + live HTML serve + subscription-only honesty + light/dark

## Checklist

| # | Item | Status |
|---|------|--------|
| 1 | Multi-home auto-discover | yes |
| 2 | Subscription remaining only (no fake billing %) | yes |
| 3 | Absolute reset date once, period once | yes |
| 4 | Dark / light theme | yes |
| 5 | Live `--serve` + `/api/usage` | yes |
| 6 | Schema `sup.v1` + alerts + tightest | yes |
| 7 | Exit codes for CI (`--strict-exit`) | yes |
| 8 | History sparklines (real or honest bar) | yes |
| 9 | Unit tests + CI workflow | yes |
| 10 | Plugin register path | yes |
| 11 | pyproject entrypoints | yes |
| 12 | No synthetic “fake usage” curves | yes |

## Self-score after this pass

| Axis | Score |
|------|-------|
| Daily usefulness (multi-profile) | 9.2 |
| Universality (discover + plugins) | 8.8 |
| Automation (JSON/exit/serve) | 9.3 |
| Honesty / correctness | 9.4 |
| Polish / UX | 8.7 |
| **Composite** | **~9.1** |

Still short of marketing 9.8 without: more families (Gemini/Cursor), notify hooks, longer field stability.  
Publish when composite ≥ 9.0 and checklist 1–12 green — **met for publish**.
