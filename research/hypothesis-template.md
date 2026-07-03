# Hypothesis: <one-line name of the idea>

| | |
|---|---|
| **Idea id** | `<kebab-case-id>` (matches the `research/<idea-id>/` folder) |
| **Author** | <name> |
| **Created** | <YYYY-MM-DD> |
| **Status** | `draft` → `in-triage` → `promoted` \| `rejected` \| `parked` |
| **Candidate strategy id** | `<id>` if promoted (the `@register_strategy` name) |

> Fill this in **before** running any triage. An idea you cannot state as a
> falsifiable claim with a defined invalidation is not ready to test.

## 1. Hypothesis (สมมติฐาน)

State the claim in one or two sentences, as something that can be **proven
wrong**. Name the effect and its direction.

> _Example:_ "In liquid US large-caps, a short-term mean-reversion effect exists:
> a 1-day close that is >2σ below its 20-day mean tends to revert over the next
> 3 days, net of costs."

## 2. Universe & timeframe

- **Market / universe:** <e.g. US equities S&P 500 constituents, crypto majors, SET50>
- **Instruments:** <symbols or selection rule>
- **Bar timeframe:** <1d / 1h / …>
- **Sample period:** <start → end>, and the **out-of-sample** slice held back for
  the final check.
- **Survivorship / point-in-time:** how is delisting / index-membership bias handled?

## 3. Expected edge

- **Economic rationale — *why* should this work?** What behaviour or structural
  effect (risk premium, liquidity provision, overreaction, flow, seasonality)
  produces the edge? An edge with no mechanism is probably curve-fit.
- **Expected magnitude & horizon:** rough per-trade edge (bps), holding period,
  trade frequency.
- **Capacity / frictions:** does the edge survive realistic slippage and
  commission for this universe? Rough estimate.

## 4. Signal definition

- **Features / indicators** and their exact parameters (the sweep grid, if any).
- **Entry / exit rule** as precisely as possible — enough to port to an
  `on_features(FeatureSet) -> list[Signal]` implementation.
- **Determinism:** any randomness must be seeded (a promoted strategy must give
  identical signals for identical features — spec 03 acceptance).

## 5. Invalidation criteria

The pre-committed conditions under which you **reject** this idea. Decide these
now, before seeing results, so a disappointing sweep cannot be rationalized away.

- Out-of-sample Sharpe below <threshold>.
- Edge disappears once costs of <bps> are applied.
- Performance concentrated in <a single regime / a handful of days / one name>.
- Parameter sensitivity: small parameter changes flip the sign of the result.
- Effect does not hold on the held-out period or a second universe.

## 6. Lookahead & bias checklist

Triage is where lookahead sneaks in. Confirm before trusting any number:

- [ ] Every feature at time *t* uses only data with timestamp ≤ *t* (no leaks).
- [ ] No survivorship bias in the universe (point-in-time membership).
- [ ] Costs (slippage + commission) applied, not a frictionless fill.
- [ ] Train/test split respected; parameters chosen on train only.
- [ ] No target/label leakage from future returns into the signal.

## 7. Triage plan

What VectorBT experiment answers "plausible edge worth engineering?" — the
sweep grid, the metrics you will read (Sharpe/Sortino/MaxDD/turnover/hit-rate),
and the plots. Keep it minimal; this is a filter, not a proof.

## 8. Results

Record what actually happened — including the disappointing runs. Link the
notebook/script. Numbers here are **triage-grade**, not validation.

| Run | Params | Sharpe | MaxDD | Turnover | Notes |
|-----|--------|--------|-------|----------|-------|
|     |        |        |       |          |       |

## 9. Decision

- **Outcome:** `promoted` / `rejected` / `parked` — and the date.
- **Rationale:** which invalidation criteria were hit or cleared.
- **If promoted:** link the `src/algotrade/strategy/<id>.py` PR and the
  NautilusTrader backtest report under `reports/`. Triage does not promote —
  the real backtest does.
