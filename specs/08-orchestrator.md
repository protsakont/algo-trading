# 08 — Orchestrator (`src/algotrade/orchestrator/`)

## Responsibility
Composition root + strategy lifecycle with promotion gates:
`RESEARCH → BACKTEST → PAPER → LIVE`

## Components
- `wiring.py` — builds the full object graph from `AppConfig` (the only place concretes are imported).
- `lifecycle.py` — `StrategyStage(Enum)` + `PromotionGate` evaluations; stage persisted in `state/strategies.json` (P0) with schema validation.
- `runner.py` — CLI entry points: `algotrade backtest <strategy_id>`, `algotrade paper <strategy_id>`, `algotrade promote <strategy_id>`, `algotrade halt`, `algotrade status`.

## Promotion gates (config-driven thresholds; defaults below)
| Transition | Gate criteria (all required) |
|---|---|
| RESEARCH → BACKTEST | strategy registered, config valid, unit tests for the strategy exist & pass |
| BACKTEST → PAPER | OOS Sharpe ≥ 1.0, max DD ≤ 20%, ≥ 100 trades, walk-forward OOS positive, report artifact present |
| PAPER → LIVE | ≥ 30 paper-trading days, paper Sharpe ≥ 0.5, tracking error vs backtest within tolerance, `RiskConfig.live_enabled=true`, manual `--confirm-live` flag |

Demotion: any kill-switch trip in PAPER/LIVE demotes the strategy to BACKTEST and requires re-promotion.

## Rules
- Gates are evaluated from persisted artifacts (backtest reports, paper logs) — never self-reported values.
- `promote` prints a human-readable gate checklist (pass/fail per criterion) before acting.
- LIVE refuses to start unless `TRADING_MODE=live` AND stage == LIVE AND kill switch clear.
- `algotrade halt` trips the kill switch immediately (routes through `IKillSwitch`; no second halt mechanism).

## Requirements & acceptance criteria (P0)
- [ ] Wiring builds full graph from `config/example.yaml`; architecture test still passes
- [ ] Each gate criterion individually failing blocks promotion with a named reason (parametrized tests)
- [ ] Demotion on kill-switch trip covered by test
- [ ] `algotrade status` lists strategies, stages, last run_id
- [ ] Corrupt/invalid state file → `ConfigError` with friendly message; backup written, no state loss
