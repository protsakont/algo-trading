# Algo-Trading System — Claude Code Project Instructions

## What this is
A Python algorithmic trading system built as a team of cooperating agents:
Data → Strategy → Backtest → Risk → Execution → Monitoring, coordinated by an Orchestrator.
All specs live in `specs/`. Read `specs/00-overview.md` first, then the spec for the module you are working on.
Specs are partly in Thai; treat them as the source of truth for requirements.
This repo ships spec-only — if `src/` does not exist yet, start with milestone M1 (skeleton + core contracts) per `specs/00-overview.md`.
Before M2/M5 work, check the Open Questions in `specs/00-overview.md` (market/universe, data vendor, broker) — some are blocking and need the human's answer.

## Stack (decided — do not substitute without an ADR)
- Python 3.12+, managed with `uv`
- **nautilus_trader** — event-driven backtest + live execution backbone (backtest/paper/live parity)
- **vectorbt** (open-source) — fast vectorized signal triage ONLY (research layer, never final validation)
- **polars** for data pipelines; **pandas** only at library boundaries that require it
- **pydantic v2** — all DTOs, configs, and message contracts
- **pytest** + **pytest-mock** — unit tests with expressive assertions (`pytest.approx`, clear messages)
- **structlog** — structured JSON logging
- Lint/format: **ruff** (line length 100); type-check: **mypy --strict** on `src/`

## Commands
```bash
uv sync                          # install deps
uv run pytest -q                 # run all tests
uv run pytest tests/unit -q      # fast loop (integration tests are marked and excluded)
uv run pytest tests/unit/risk/test_limits.py::test_max_drawdown_trips -q   # single test
uv run pytest --cov=src/algotrade --cov-report=term-missing   # coverage
uv run ruff check . && uv run ruff format --check .
uv run mypy src/
```
Coverage floors (CI-enforced, override the global 80% rule): **85% overall, 90% on `risk/` and `execution/`**.

## Repository layout (create exactly this)
```
src/algotrade/
  domain/          # DTOs, enums, value objects (pydantic). Zero I/O.
  interfaces/      # typing.Protocol definitions only
  data/            # Data Agent: feeds, adapters, feature store
  strategy/        # Strategy Agent: signal generators
  backtest/        # Backtest Agent: nautilus wiring, walk-forward, reports
  risk/            # Risk Agent: sizing, limits, pre-trade checks
  execution/       # Execution Agent: order lifecycle, broker gateways
  monitoring/      # Monitoring Agent: P&L, health, alerts, kill switch
  orchestrator/    # lifecycle stages + promotion gates
  config/          # pydantic-settings models, YAML loaders
tests/
  unit/            # mirrors src layout; mock all I/O
  integration/     # marked @pytest.mark.integration
reports/gates/     # stage-gate evidence per strategy (specs/00)
```
Where `specs/01-architecture.md`'s layout sketch differs from the above (it shows `domain/ports.py` and
`infra/` instead of `interfaces/`, `config/`, `orchestrator/`), **this layout wins** — specs 08 and 09
already assume it. Protocols go in `interfaces/`, the composition root in `orchestrator/wiring.py`.
Record this (and any future spec deviation) in `specs/DECISIONS.md`.

## Design rules (non-negotiable)
1. **Constructor injection only.** No service locators, no module-level singletons, no import-time side effects.
2. **Small interfaces.** Every cross-module dependency goes through a `Protocol` in `src/algotrade/interfaces/`. Use the spec names — no `I` prefix: `DataFeed`, `FeatureStore`, `Strategy`, `RiskChecker`, `PositionSizer`, `BrokerGateway`, `AlertSink` (signatures in `specs/01-architecture.md`). Keep each protocol ≤ 5 methods.
3. **DTOs separate from engine/persistence types.** Never leak nautilus/vectorbt objects across module boundaries — map to domain DTOs at the edge.
4. **Risk always wins.** Execution can never bypass `RiskChecker`. The veto is enforced in orchestrator wiring, not by convention. `RiskChecker.check()` returns a verdict — it never throws to reject.
5. **No raw exceptions to callers/users.** Catch at boundaries, map to the `AlgoTradeError` hierarchy, log with context.
6. **Config-driven.** Strategy params, universe, limits come from validated config — never hard-coded.
7. **Parameterize everything** touching storage (SQL parameters only); validate all external input with pydantic.
8. **Money is never `float`.** Prices/quantities/P&L in domain DTOs use `Decimal` (map to engine-native types only inside adapters).
9. **Secrets** only via environment variables (`pydantic-settings`); never committed, never logged.

## Engineering loop (how you work)
Follow `specs/09-engineering-loop.md` strictly. Summary:
plan → red test → implement → green → review with the `qa-reviewer` subagent → refactor → commit.
- Work specs in order 01 → 08; each unchecked acceptance criterion in a spec is one task.
- One criterion = one commit, referencing the spec: `feat(risk): max drawdown rule trips kill switch (spec 05)`.
- Flip the criterion's `[ ]` → `[x]` in the spec file **in the same commit** as the implementation.
- If a spec is ambiguous, record the ambiguity + your resolution in `specs/DECISIONS.md` (ADR-lite: context, decision, why) and proceed.
- Never commit with failing tests or mypy errors.

**Stop and ask the human** before: changing a Protocol signature already implemented elsewhere,
weakening any risk rule/gate/safety rail, adding a dependency not in the stack, or anything
touching real broker credentials or live trading.

## Subagents
Definitions in `.claude/agents/`. Delegate work matching each agent's charter
(e.g. `risk-engineer` for anything under `src/algotrade/risk/`; `qa-reviewer` before every commit).

## Definition of Done (every task)
- [ ] Acceptance criteria in the relevant spec are checked off
- [ ] Unit tests written first, all passing; mocks for every I/O boundary
- [ ] `ruff` clean, `mypy --strict` clean
- [ ] No TODOs without a linked spec item
- [ ] `qa-reviewer` pass completed

## Safety rails
- All trading code paths default to **paper mode**; going live requires explicit `TRADING_MODE=live` env var + config flag + `I_UNDERSTAND_LIVE_TRADING=true` (specs/01) + passing all Orchestrator gates (`specs/08-orchestrator.md`).
- Never remove or weaken a risk limit to make a test pass.
- README must state this system is not financial advice; live use is the operator's own decision.
