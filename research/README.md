# research/

The **triage layer** (spec 03 workflow). Everything here lives *outside* `src/`
and is **never deployed** — it exists to kill bad ideas cheaply before they cost
engineering time.

## The loop

1. **Write a hypothesis doc first.** Copy [`hypothesis-template.md`](hypothesis-template.md)
   to `research/<idea-id>/hypothesis.md` and fill it in *before* running anything.
   An idea without a written, falsifiable hypothesis is not ready for triage.
2. **Triage with VectorBT.** Fast, vectorized signal exploration — parameter
   sweeps, quick equity curves, sanity plots. This is research only; VectorBT is
   never the final word (see `CLAUDE.md`: it is "fast vectorized signal triage
   ONLY, never final validation").
3. **Decide.** Record the outcome in the hypothesis doc's *Results* and
   *Decision* sections: promote, iterate, or reject. Rejections stay — a killed
   idea with evidence is worth as much as a promoted one.
4. **Promote survivors.** Only ideas that pass triage get ported to a real
   `Strategy` class under `src/algotrade/strategy/` and validated for real on the
   NautilusTrader backtest engine (spec 04). See
   [`../docs/adding-a-strategy.md`](../docs/adding-a-strategy.md).

## Why triage ≠ validation

VectorBT triage is optimistic by construction: it is easy to let future data
leak in, to overfit a sweep, or to ignore costs. It answers *"is there plausibly
an edge here worth the engineering?"* — not *"is this edge real and tradeable?"*
That second question is the backtest engine's job, on the same DTOs the live
system uses. Never promote on triage numbers alone.

## Layout

```
research/
  README.md
  hypothesis-template.md          # copy this per idea
  <idea-id>/
    hypothesis.md                 # filled-in template — the source of truth
    *.ipynb / *.py                # throwaway triage notebooks/scripts
```

Triage code here is not held to `src/` standards (no coverage floor, no
`mypy --strict`), but the hypothesis doc is the durable artifact — keep it
honest and up to date.
