"""SMA crossover baseline (spec 03): FeatureSet -> Signal only. Deterministic,
no knowledge of orders, brokers, or sizing."""

from datetime import UTC, datetime

import pytest

from algotrade.domain.dto import FeatureSet
from algotrade.domain.enums import SignalDirection
from algotrade.strategy.registry import build_strategy
from algotrade.strategy.sma_cross import SmaCrossConfig, SmaCrossStrategy

TS = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


def make_features(fast: float | None, slow: float | None) -> FeatureSet:
    features: dict[str, float] = {}
    if fast is not None:
        features["sma_10"] = fast
    if slow is not None:
        features["sma_30"] = slow
    return FeatureSet(symbol="AAPL", timestamp=TS, features=features)


@pytest.fixture
def strategy() -> SmaCrossStrategy:
    return SmaCrossStrategy(SmaCrossConfig(fast_window=10, slow_window=30))


class TestSignals:
    def test_fast_above_slow_is_long(self, strategy: SmaCrossStrategy) -> None:
        [signal] = strategy.on_features(make_features(fast=105.0, slow=100.0))
        assert signal.direction is SignalDirection.LONG
        assert 0 < signal.strength <= 1
        assert signal.strategy_id == "sma_cross"
        assert signal.symbol == "AAPL"
        assert signal.timestamp == TS

    def test_fast_below_slow_is_short(self, strategy: SmaCrossStrategy) -> None:
        [signal] = strategy.on_features(make_features(fast=95.0, slow=100.0))
        assert signal.direction is SignalDirection.SHORT
        assert -1 <= signal.strength < 0

    def test_equal_smas_are_flat(self, strategy: SmaCrossStrategy) -> None:
        [signal] = strategy.on_features(make_features(fast=100.0, slow=100.0))
        assert signal.direction is SignalDirection.FLAT
        assert signal.strength == 0.0

    def test_strength_grows_with_spread_and_stays_bounded(self, strategy: SmaCrossStrategy) -> None:
        [narrow] = strategy.on_features(make_features(fast=100.5, slow=100.0))
        [wide] = strategy.on_features(make_features(fast=150.0, slow=100.0))
        [extreme] = strategy.on_features(make_features(fast=100000.0, slow=1.0))
        assert 0 < narrow.strength < wide.strength <= 1
        assert extreme.strength == 1.0

    def test_metadata_records_the_smas_used(self, strategy: SmaCrossStrategy) -> None:
        [signal] = strategy.on_features(make_features(fast=105.0, slow=100.0))
        assert signal.metadata["sma_10"] == "105.0"
        assert signal.metadata["sma_30"] == "100.0"


class TestWarmup:
    @pytest.mark.parametrize(("fast", "slow"), [(None, 100.0), (105.0, None), (None, None)])
    def test_missing_smas_produce_no_signal(
        self, strategy: SmaCrossStrategy, fast: float | None, slow: float | None
    ) -> None:
        """During feature warmup the honest output is silence, not FLAT."""
        assert strategy.on_features(make_features(fast, slow)) == []

    @pytest.mark.parametrize("slow", [0.0, -100.0])
    def test_degenerate_slow_sma_produces_no_signal(
        self, strategy: SmaCrossStrategy, slow: float
    ) -> None:
        """A non-positive price SMA is broken data, not a FLAT opinion."""
        assert strategy.on_features(make_features(fast=5.0, slow=slow)) == []

    def test_short_strength_clamps_at_minus_one(self, strategy: SmaCrossStrategy) -> None:
        [signal] = strategy.on_features(make_features(fast=-50.0, slow=100.0))
        assert signal.direction is SignalDirection.SHORT
        assert signal.strength == -1.0


class TestDeterminism:
    def test_same_features_same_signals(self, strategy: SmaCrossStrategy) -> None:
        """Spec 03 acceptance: repeated on_features over identical features
        yields identical signals."""
        features = make_features(fast=103.7, slow=101.2)
        assert strategy.on_features(features) == strategy.on_features(features)


class TestConfig:
    def test_fast_must_be_shorter_than_slow(self) -> None:
        with pytest.raises(ValueError, match="fast_window"):
            SmaCrossConfig(fast_window=30, slow_window=10)

    def test_loader_builds_sma_cross_from_params(self) -> None:
        strategy = build_strategy("sma_cross", {"fast_window": 5, "slow_window": 20})
        assert isinstance(strategy, SmaCrossStrategy)
        [signal] = strategy.on_features(
            FeatureSet(symbol="AAPL", timestamp=TS, features={"sma_5": 11.0, "sma_20": 10.0})
        )
        assert signal.direction is SignalDirection.LONG
