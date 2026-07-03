"""PolarsFeatureStore (spec 02): vectorized indicators with a proven
no-lookahead property — the feature at time t must be identical whether or not
any data after t exists."""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from algotrade.data.features import FeatureConfig, PolarsFeatureStore
from algotrade.domain.dto import Bar
from algotrade.domain.errors import DataFeedError

T0 = datetime(2026, 1, 5, tzinfo=UTC)


def make_bars(closes: list[str]) -> list[Bar]:
    return [
        Bar(
            symbol="AAPL",
            timestamp=T0 + timedelta(days=i),
            timeframe="1d",
            open=Decimal(c),
            high=Decimal(c) + 1,
            low=Decimal(c) - 1,
            close=Decimal(c),
            volume=Decimal("1000"),
        )
        for i, c in enumerate(closes)
    ]


@pytest.fixture
def store() -> PolarsFeatureStore:
    return PolarsFeatureStore(FeatureConfig(sma_windows=(3,), vol_window=3))


class TestCorrectness:
    def test_sma_matches_hand_computation(self, store: PolarsFeatureStore) -> None:
        features = store.compute(make_bars(["100", "102", "104", "106"]))
        assert features.features["sma_3"] == pytest.approx((102 + 104 + 106) / 3)

    def test_log_return_matches_hand_computation(self, store: PolarsFeatureStore) -> None:
        features = store.compute(make_bars(["100", "110"]))
        assert features.features["log_return"] == pytest.approx(math.log(110 / 100))

    def test_feature_set_is_stamped_with_last_bar_time(self, store: PolarsFeatureStore) -> None:
        bars = make_bars(["100", "101", "102", "103"])
        assert store.compute(bars).timestamp == bars[-1].timestamp
        assert store.compute(bars).symbol == "AAPL"

    def test_warmup_features_are_omitted_not_faked(self, store: PolarsFeatureStore) -> None:
        """With fewer bars than the window, the feature must be absent — never
        a fabricated partial value."""
        features = store.compute(make_bars(["100", "102"]))
        assert "sma_3" not in features.features
        assert "log_return" in features.features


class TestNoLookahead:
    def test_every_feature_is_identical_with_and_without_future_data(self) -> None:
        """Spec 02 P0: feature at time t uses data <= t only. For every prefix
        length k, computing on bars[:k] must equal row k-1 of the full frame."""
        store = PolarsFeatureStore(FeatureConfig(sma_windows=(3, 5), vol_window=4))
        closes = [str(100 + ((i * 7) % 13) - 6) for i in range(30)]  # deterministic wiggle
        bars = make_bars(closes)

        full = store.compute_frame(bars)
        feature_columns = [c for c in full.columns if c != "timestamp"]

        for k in (5, 12, 29):
            prefix_last = store.compute_frame(bars[: k + 1]).row(k, named=True)
            full_row = full.row(k, named=True)
            for column in feature_columns:
                expected, actual = full_row[column], prefix_last[column]
                if expected is None:
                    assert actual is None, f"{column}@{k}: lookahead-dependent null-ness"
                else:
                    assert actual == pytest.approx(expected), (
                        f"{column} at row {k} changed when future bars were added — lookahead!"
                    )

    def test_deterministic_across_repeated_calls(self, store: PolarsFeatureStore) -> None:
        bars = make_bars(["100", "102", "104", "103", "105"])
        assert store.compute(bars) == store.compute(bars)

    def test_shuffled_input_yields_same_result_and_latest_timestamp(
        self, store: PolarsFeatureStore
    ) -> None:
        """Regression (qa M1): reversed input once stamped the FeatureSet with
        the FIRST bar's time while features used the whole series — a feature
        labeled as known at t that was computed from data after t."""
        bars = make_bars(["100", "102", "104", "106", "108"])
        shuffled = [bars[3], bars[0], bars[4], bars[1], bars[2]]

        result = store.compute(shuffled)

        assert result == store.compute(bars)
        assert result.timestamp == max(b.timestamp for b in bars)


class TestProtocolConformance:
    def test_store_satisfies_feature_store_protocol(self, store: PolarsFeatureStore) -> None:
        from algotrade.interfaces import FeatureStore

        assert isinstance(store, FeatureStore)


class TestValidation:
    def test_empty_bars_raise_data_feed_error(self, store: PolarsFeatureStore) -> None:
        with pytest.raises(DataFeedError, match="empty"):
            store.compute([])

    def test_mixed_symbols_raise_data_feed_error(self, store: PolarsFeatureStore) -> None:
        bars = make_bars(["100", "101"])
        alien = bars[1].model_copy(update={"symbol": "MSFT"})
        with pytest.raises(DataFeedError, match="symbol"):
            store.compute([bars[0], alien])

    def test_config_rejects_nonsense_windows(self) -> None:
        with pytest.raises(ValueError):
            FeatureConfig(sma_windows=(0,), vol_window=3)
