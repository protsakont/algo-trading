"""PolarsFeatureStore (spec 02): vectorized indicators over bars.

No-lookahead by construction: every expression uses only rolling/shift
operations over past values — window k at row t sees rows (t-k+1)..t. Input is
sorted internally, and the FeatureSet timestamp is taken from the same sorted
order, so the stamp can never predate the data used. The property is pinned by
tests comparing prefix computations against the full frame, including shuffled
input.

Feature values are analytics, not money, so float is acceptable here (the
Decimal rule applies to prices/quantities crossing module boundaries).
"""

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, field_validator

from algotrade.domain.dto import Bar, FeatureSet
from algotrade.domain.errors import DataFeedError


class FeatureConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    sma_windows: tuple[int, ...] = Field(default=(20, 50), min_length=1)
    vol_window: int = Field(default=20, gt=1)

    @field_validator("sma_windows")
    @classmethod
    def _windows_positive(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(window <= 0 for window in value):
            raise ValueError(f"sma_windows must be positive, got {value}")
        return value


class PolarsFeatureStore:
    def __init__(self, config: FeatureConfig | None = None) -> None:
        self._config = config or FeatureConfig()

    def compute(self, bars: list[Bar]) -> FeatureSet:
        """Features as of the LAST bar (by timestamp, regardless of input
        order). Warmup features (window longer than the available history) are
        omitted, never fabricated."""
        ordered = self._ordered(bars)
        frame = self._frame(ordered)
        last = frame.row(frame.height - 1, named=True)
        features = {
            name: float(value)
            for name, value in last.items()
            if name != "timestamp" and value is not None
        }
        return FeatureSet(
            symbol=ordered[0].symbol, timestamp=ordered[-1].timestamp, features=features
        )

    def compute_frame(self, bars: list[Bar]) -> pl.DataFrame:
        """One row per bar in timestamp order: the feature values as they would
        have been known at that bar's close. Used by compute() and by the
        lookahead tests."""
        return self._frame(self._ordered(bars))

    def _ordered(self, bars: list[Bar]) -> list[Bar]:
        if not bars:
            raise DataFeedError("cannot compute features on an empty bar list")
        symbols = {b.symbol for b in bars}
        if len(symbols) > 1:
            raise DataFeedError(f"bars must share one symbol, got {sorted(symbols)}")
        return sorted(bars, key=lambda b: b.timestamp)

    def _frame(self, ordered: list[Bar]) -> pl.DataFrame:
        close = pl.col("close")
        log_return = (close / close.shift(1)).log()
        vol_window = self._config.vol_window
        expressions = [
            *[
                close.rolling_mean(window_size=w, min_samples=w).alias(f"sma_{w}")
                for w in self._config.sma_windows
            ],
            log_return.alias("log_return"),
            log_return.rolling_std(window_size=vol_window, min_samples=vol_window).alias(
                f"vol_{vol_window}"
            ),
        ]
        base = pl.DataFrame(
            {
                "timestamp": [b.timestamp for b in ordered],
                "close": [float(b.close) for b in ordered],
            }
        )
        return base.with_columns(expressions).drop("close")
