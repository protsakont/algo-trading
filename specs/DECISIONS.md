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

## D-006 — Vendor adapter deferred; ingest built against a VendorSource protocol
- **Context:** spec 02 P0 item 1 ("ParquetDataFeed + VendorIngestJob") parenthesizes the
  vendor with the blocking Open Question in specs/00 (market/universe -> vendor).
- **Decision:** ParquetDataFeed and VendorIngestJob are implemented now; the job consumes
  a data-module-internal `VendorSource` protocol (raw rows: Decimal/int/str values,
  tz-aware timestamps — floats rejected by the integrity check). The concrete vendor
  adapter lands once the market/vendor question is answered; P0 checkbox 1 stays open
  until then.
- **Why:** everything except the vendor HTTP/SDK call is vendor-agnostic; blocking all of
  M2 on the vendor choice would serialize work needlessly.

## D-007 — tzdata added as a dependency
- **Context:** polars requires the IANA timezone database for tz-aware dtypes; Windows
  Python installs don't ship one (uv-managed CPython included).
- **Decision:** depend on `tzdata` (pure-data package, no code).
- **Why:** platform shim for a stack-listed library, not a new library choice; harmless
  on Linux/macOS where the system database exists.

## D-008 — Unit-test conventions vs spec 02 acceptance wording
- **Context:** spec 02 acceptance says fixtures live in `tests/fixtures/` and unit tests
  run with `-m unit`; the project convention (CLAUDE.md/M1) is directory-based selection
  (`tests/unit/`) with an `integration` marker excluded from the fast gate.
- **Decision:** keep directory-based selection and inline builder helpers; `tests/fixtures/`
  is reserved for on-disk data files when a vendor adapter needs them. No `unit` marker.
- **Why:** one selection mechanism, no drift between marker and directory; the spec's
  intent (no network in unit tests) is enforced by construction (StubVendor + tmp_path).

## D-009 — Spec 04 narrowings and deferrals (M3 baseline)
- **Context:** spec 04 P0 says `BacktestRunner(strategy_id, universe, period, config)`,
  costs "per market", and an acceptance criterion demands a working CLI.
- **Decision:**
  - v1 runner is single-symbol (`symbol: str`); multi-symbol universes arrive with
    portfolio-level backtests. The P0 checkbox is checked with this narrowing recorded.
  - One global slippage/commission pair per run (config), not per market — same
    single-market narrowing.
  - CLI (`algotrade backtest run ...`) is deferred to spec 08, whose runner.py owns all
    CLI entry points; the spec 04 acceptance criterion stays open until then.
  - Execution model — market orders fill at the same bar's close, zero latency — is
    declared in every report (`execution_model` field), like slippage/commission.
  - `BacktestConfig.seed` is reserved: no code path consumes randomness today; it will
    drive the engine fill model when stochastic fills arrive.
- **Why:** the narrowings keep M3 shippable without weakening any declared assumption;
  each is visible in the report artifact rather than buried in code.
