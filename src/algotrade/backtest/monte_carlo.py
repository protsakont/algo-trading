"""Monte Carlo trade-order resampling (spec 04 P1).

Reordering the realized trades leaves the total P&L unchanged but reshapes the
equity path, so the drawdown depends on sequencing. Resampling the order many
times and collecting the MaxDD gives a distribution: if the observed drawdown
sits far below the tail, the strategy simply got a lucky ordering.

Trades are resampled *without* replacement (a permutation of the actual round
trips) — this isolates path/sequence risk while holding the trade set fixed.
Drawdown is a ratio, so computed in float like the other backtest analytics;
the observed value uses the same ``1 - equity/peak`` definition as
``compute_metrics``.
"""

import random
from collections.abc import Sequence
from decimal import Decimal
from itertools import accumulate

from pydantic import BaseModel, ConfigDict

from algotrade.backtest.metrics import max_drawdown
from algotrade.domain.errors import BacktestError


class MonteCarloDrawdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    simulations: int
    seed: int
    observed_max_drawdown: float
    mean_max_drawdown: float
    median_max_drawdown: float
    p95_max_drawdown: float
    p99_max_drawdown: float
    worst_max_drawdown: float


def monte_carlo_drawdown(
    trade_pnls: Sequence[Decimal],
    starting_equity: Decimal,
    *,
    simulations: int,
    seed: int,
) -> MonteCarloDrawdown:
    """Distribution of MaxDD over ``simulations`` random orderings of the trades.

    A drawdown above 1.0 is retained rather than clamped: it means an ordering
    drove equity negative (ruin), which is exactly the tail risk this surfaces.
    """
    if len(trade_pnls) < 2:
        raise BacktestError(f"need at least 2 trades to resample order, got {len(trade_pnls)}")
    if simulations < 1:
        raise BacktestError(f"simulations must be positive, got {simulations}")
    if starting_equity <= 0:
        raise BacktestError(f"starting equity must be positive, got {starting_equity}")

    start = float(starting_equity)
    pnls = [float(p) for p in trade_pnls]

    observed = max_drawdown(_equity_curve(start, pnls))

    rng = random.Random(seed)
    order = list(pnls)
    samples = []
    for _ in range(simulations):
        rng.shuffle(order)
        samples.append(max_drawdown(_equity_curve(start, order)))
    samples.sort()

    return MonteCarloDrawdown(
        simulations=simulations,
        seed=seed,
        observed_max_drawdown=observed,
        mean_max_drawdown=sum(samples) / len(samples),
        median_max_drawdown=_percentile(samples, 50.0),
        p95_max_drawdown=_percentile(samples, 95.0),
        p99_max_drawdown=_percentile(samples, 99.0),
        worst_max_drawdown=samples[-1],
    )


def _equity_curve(start: float, pnls: Sequence[float]) -> list[float]:
    """Trade-level equity: the starting capital followed by the running total
    after each closed trade (the input to the shared ``max_drawdown``)."""
    return list(accumulate(pnls, initial=start))


def _percentile(ordered: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted sequence."""
    if len(ordered) == 1:
        return ordered[0]
    rank = (q / 100.0) * (len(ordered) - 1)
    low = int(rank)
    if low >= len(ordered) - 1:
        return ordered[-1]
    frac = rank - low
    return ordered[low] + (ordered[low + 1] - ordered[low]) * frac
