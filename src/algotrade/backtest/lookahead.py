"""Lookahead detector (spec 04): perturb the FUTURE, and any change in PAST
signals convicts the pipeline of using future data.

This guard is ONE-SIDED: a violation proves lookahead; an empty result proves
nothing. Known evasion classes (do not treat a pass as certification):
- leaks entirely BEFORE the earliest checkpoint (bar i reading bar i+1, both
  pre-checkpoint) are invisible to that checkpoint — sweep multiple
  checkpoints (the default) to shrink, not eliminate, this window;
- a cheater consuming only properties the perturbation preserves survives it;
  the per-bar sign-varying bumps below (applied to OHLC AND volume) break
  uniform-scale invariants, but cannot break every conceivable invariant.
It is a tripwire in front of the promotion gates, not a proof of honesty.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from algotrade.domain.dto import Bar, Signal
from algotrade.domain.errors import BacktestError
from algotrade.interfaces import FeatureStore, Strategy

# A pipeline maps bars -> one signal tuple per bar (what the strategy said at
# each bar's close).
SignalPipeline = Callable[[list[Bar]], list[tuple[Signal, ...]]]

# Deterministic, sign-varying factors so relative structure between future
# bars is NOT preserved (a uniform scale would keep future ratios intact).
_FACTORS = (Decimal("1.11"), Decimal("0.93"), Decimal("1.06"), Decimal("0.89"))


class LookaheadViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    detail: str


def streaming_pipeline(
    strategy_factory: Callable[[], Strategy], feature_store: FeatureStore
) -> SignalPipeline:
    """The honest reference pipeline: at each bar, features are computed from
    the prefix only and fed to a fresh strategy stream."""

    def run(bars: list[Bar]) -> list[tuple[Signal, ...]]:
        strategy = strategy_factory()
        return [
            tuple(strategy.on_features(feature_store.compute(bars[: i + 1])))
            for i in range(len(bars))
        ]

    return run


def _bump(bar: Bar, index: int) -> Bar:
    factor = _FACTORS[index % len(_FACTORS)]
    return bar.model_copy(
        update={
            "open": bar.open * factor,
            "high": bar.high * factor,
            "low": bar.low * factor,
            "close": bar.close * factor,
            "volume": bar.volume * factor,
        }
    )


def detect_lookahead(
    pipeline: SignalPipeline, bars: Sequence[Bar], checkpoints: int | Sequence[int]
) -> list[LookaheadViolation]:
    """For each checkpoint, run the pipeline on the original bars and on bars
    with everything AFTER the checkpoint perturbed; report every
    pre-checkpoint bar whose signals differ."""
    points = [checkpoints] if isinstance(checkpoints, int) else list(checkpoints)
    if not points:
        raise BacktestError("at least one checkpoint is required")
    for point in points:
        if not 0 < point < len(bars):
            raise BacktestError(f"checkpoint must split the series, got {point} of {len(bars)}")

    original = list(bars)
    baseline = pipeline(original)
    if len(baseline) != len(original):
        raise BacktestError("pipeline must emit exactly one signal tuple per bar")

    violations: dict[int, LookaheadViolation] = {}
    for point in points:
        mutated = original[:point] + [_bump(b, i) for i, b in enumerate(original[point:])]
        perturbed = pipeline(mutated)
        if len(perturbed) != len(mutated):
            raise BacktestError("pipeline must emit exactly one signal tuple per bar")
        for i in range(point):
            if i not in violations and baseline[i] != perturbed[i]:
                violations[i] = LookaheadViolation(
                    timestamp=original[i].timestamp,
                    detail=(
                        f"signals at bar {i} ({original[i].timestamp.isoformat()}) changed "
                        f"when bars after index {point} were perturbed: "
                        f"{baseline[i]!r} != {perturbed[i]!r}"
                    ),
                )
    return [violations[i] for i in sorted(violations)]
