"""Backtest metrics (spec 04): pure functions over the equity curve and round
trips. Ratios are analytics, so float; population statistics throughout."""

import math
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

from pydantic import BaseModel, ConfigDict

from algotrade.backtest.accounting import EquityPoint, RoundTrip
from algotrade.domain.errors import BacktestError


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    turnover: float
    win_rate: float
    exposure: float
    trade_count: int


def compute_metrics(
    curve: Sequence[EquityPoint],
    round_trips: Sequence[RoundTrip],
    traded_notional: Decimal,
    periods_per_year: int,
) -> BacktestMetrics:
    if len(curve) < 2:
        raise BacktestError(f"equity curve needs at least 2 points, got {len(curve)}")
    equities = [float(p.equity) for p in curve]
    if any(equity <= 0 for equity in equities):
        # A blown-up account is a degenerate result: refuse to compute
        # flattering statistics over the surviving prefix.
        raise BacktestError("equity went non-positive during the run - metrics are undefined")

    returns = [b / a - 1 for a, b in pairwise(equities)]
    total_return = equities[-1] / equities[0] - 1

    # Log-space with a clamped exponent: short curves with huge returns
    # annualize into numbers beyond float range (raw ** raises OverflowError).
    _MAX_LOG_GROWTH = 690.0  # exp(690) ~ 1e299, still finite
    log_growth = (periods_per_year / len(returns)) * math.log(equities[-1] / equities[0])
    cagr = math.exp(min(log_growth, _MAX_LOG_GROWTH)) - 1

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    std = math.sqrt(variance)
    sharpe = (mean / std) * math.sqrt(periods_per_year) if std else 0.0

    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in returns) / len(returns))
    sortino = (mean / downside) * math.sqrt(periods_per_year) if downside else 0.0

    peak = equities[0]
    max_drawdown = 0.0
    for equity in equities:
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, 1 - equity / peak)

    average_equity = sum(equities) / len(equities)
    turnover = float(traded_notional) / average_equity if average_equity else 0.0

    wins = sum(1 for trip in round_trips if trip.is_win)
    win_rate = wins / len(round_trips) if round_trips else 0.0
    exposure = sum(1 for p in curve if p.position != 0) / len(curve)

    return BacktestMetrics(
        total_return=total_return,
        cagr=cagr,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_drawdown,
        turnover=turnover,
        win_rate=win_rate,
        exposure=exposure,
        trade_count=len(round_trips),
    )
