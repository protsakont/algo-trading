# Decisions (ADR-lite)

Ambiguities found in specs and how they were resolved (specs/09, loop step 1).
Format per entry: context, decision, why.

## D-001 — Repository layout: CLAUDE.md wins over spec 01 sketch
- **Context:** spec 01 sketches `domain/ports.py` + `infra/{config,composition}.py`;
  CLAUDE.md, spec 08 (`orchestrator/`), and spec 09 (delegation map with `interfaces/`)
  assume `interfaces/`, `config/`, `orchestrator/`.
- **Decision:** Protocols live in `src/algotrade/interfaces/protocols.py`, settings in
  `src/algotrade/config/`, composition root in `src/algotrade/orchestrator/wiring.py`.
- **Why:** two of three specs plus CLAUDE.md agree; changing spec 01's sketch is lower
  cost than contradicting the delegation map and orchestrator spec.

## D-002 — Heavy engine dependencies deferred to first use
- **Context:** the stack decides nautilus_trader, vectorbt, polars, but M1 needs none
  of them; they are large binary installs that slow CI.
- **Decision:** M1 declares only pydantic, pydantic-settings, structlog. polars lands
  with spec 02 (M2), nautilus_trader with spec 04 (M3), vectorbt with the research
  triage layer, hypothesis with spec 05 (M4).
- **Why:** stack is unchanged (no substitution) — only install timing is deferred; the
  architecture test already fences where engine libraries may be imported.

## D-003 — OHLC sanity validation lives in the Bar DTO
- **Context:** spec 02 puts integrity checks (low <= open,close <= high) in the data
  layer's batch report; spec 01 says DTOs are pure and validated.
- **Decision:** Bar enforces OHLC sanity, positive prices, tz-aware UTC timestamps.
  The data layer still produces its batch integrity report (spec 02) from raw vendor
  rows *before* constructing Bars.
- **Why:** invalid market data must be unrepresentable inside the domain; the batch
  report remains the operator-facing artifact.

## D-004 — Live-mode guard is config-level, orchestrator gates stack on top
- **Context:** CLAUDE.md names `TRADING_MODE=live` + config flag; spec 01 adds
  `I_UNDERSTAND_LIVE_TRADING=true`.
- **Decision:** `AppSettings` refuses `TRADING_MODE=live` unless
  `I_UNDERSTAND_LIVE_TRADING=true`; spec 08 promotion gates are enforced separately in
  the orchestrator and are NOT replaced by this check.
- **Why:** defense in depth — misconfiguration fails at startup, before any wiring.

## D-005 — Signal.metadata is dict[str, str]
- **Context:** spec 03 lists `metadata` on Signal without a type.
- **Decision:** `dict[str, str]` — numeric metadata must be stringified by the strategy.
- **Why:** keeps the DTO JSON-trivial and mypy-strict friendly; widen deliberately
  (with a new decision entry) if a real strategy needs structured metadata.
