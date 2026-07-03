"""Baseline SMA crossover strategy (spec 03) — the reference implementation.

Reads ``sma_<fast>`` / ``sma_<slow>`` from the FeatureSet and emits one signal:
LONG when fast > slow, SHORT when fast < slow, FLAT when equal. Strength is
the relative spread clamped to [-1, 1]. During warmup (either SMA missing) it
emits nothing — silence, not a fabricated FLAT.
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from algotrade.domain.dto import FeatureSet, Signal
from algotrade.domain.enums import SignalDirection

from .registry import register_strategy

STRATEGY_ID = "sma_cross"


class SmaCrossConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fast_window: int = Field(default=20, gt=0)
    slow_window: int = Field(default=50, gt=0)

    @model_validator(mode="after")
    def _fast_shorter_than_slow(self) -> Self:
        if self.fast_window >= self.slow_window:
            raise ValueError(
                f"fast_window ({self.fast_window}) must be shorter than "
                f"slow_window ({self.slow_window})"
            )
        return self


@register_strategy(STRATEGY_ID, config=SmaCrossConfig)
class SmaCrossStrategy:
    """Stateless per call and deterministic: identical features always
    produce identical signals (spec 03 acceptance)."""

    def __init__(self, config: SmaCrossConfig) -> None:
        self._config = config
        self._fast_key = f"sma_{config.fast_window}"
        self._slow_key = f"sma_{config.slow_window}"

    def on_features(self, features: FeatureSet) -> list[Signal]:
        fast = features.features.get(self._fast_key)
        slow = features.features.get(self._slow_key)
        if fast is None or slow is None or slow <= 0:
            # Warmup or degenerate data (price SMAs are positive by
            # construction): silence, never a fabricated opinion.
            return []

        # Relative spread is unbounded above (+1 clamp reachable) but only
        # approaches -1 as fast -> 0, so shorts saturate later than longs.
        spread = (fast - slow) / slow
        strength = max(-1.0, min(1.0, spread))
        if strength > 0:
            direction = SignalDirection.LONG
        elif strength < 0:
            direction = SignalDirection.SHORT
        else:
            direction = SignalDirection.FLAT

        return [
            Signal(
                strategy_id=STRATEGY_ID,
                symbol=features.symbol,
                direction=direction,
                strength=strength,
                timestamp=features.timestamp,
                metadata={self._fast_key: str(fast), self._slow_key: str(slow)},
            )
        ]
