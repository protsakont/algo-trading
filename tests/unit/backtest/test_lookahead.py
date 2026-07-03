"""Lookahead detector (spec 04 acceptance): a pipeline whose past signals
change when FUTURE bars are perturbed is using future data — catch it."""

from algotrade.backtest.lookahead import detect_lookahead, streaming_pipeline
from algotrade.data.features import FeatureConfig, PolarsFeatureStore
from algotrade.domain.dto import Bar, Signal
from algotrade.domain.enums import SignalDirection
from algotrade.strategy import SmaCrossConfig, SmaCrossStrategy

from .test_runner import synthetic_bars


class TestHonestPipeline:
    def test_sma_cross_over_polars_features_has_no_lookahead(self) -> None:
        pipeline = streaming_pipeline(
            lambda: SmaCrossStrategy(SmaCrossConfig(fast_window=3, slow_window=8)),
            PolarsFeatureStore(FeatureConfig(sma_windows=(3, 8), vol_window=3)),
        )
        violations = detect_lookahead(pipeline, synthetic_bars(40), checkpoints=(13, 25, 33))
        assert violations == []


class _FullSeriesNormalizer:
    """Deliberately cheating fixture: signal strength is normalized by the
    FULL series mean — the classic whole-dataset-normalization leak."""

    def __call__(self, bars: list[Bar]) -> list[tuple[Signal, ...]]:
        full_mean = sum(float(b.close) for b in bars) / len(bars)
        signals_per_bar: list[tuple[Signal, ...]] = []
        for bar in bars:
            strength = max(-1.0, min(1.0, float(bar.close) / full_mean - 1.0))
            direction = SignalDirection.LONG if strength >= 0 else SignalDirection.SHORT
            signals_per_bar.append(
                (
                    Signal(
                        strategy_id="cheater",
                        symbol=bar.symbol,
                        direction=direction,
                        strength=strength,
                        timestamp=bar.timestamp,
                    ),
                )
            )
        return signals_per_bar


class TestCheatingPipeline:
    def test_full_series_normalization_is_detected(self) -> None:
        bars = synthetic_bars(40)
        violations = detect_lookahead(_FullSeriesNormalizer(), bars, checkpoints=(13, 25, 33))

        assert violations, "detector failed to catch whole-dataset normalization"
        assert all(v.timestamp <= bars[32].timestamp for v in violations), (
            "violations must point at signals BEFORE the latest perturbation point (33)"
        )
        assert "changed" in violations[0].detail
