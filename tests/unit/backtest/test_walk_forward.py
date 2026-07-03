"""Walk-forward runner (spec 04): rolling train/test folds, one report per
test fold, plus OOS aggregates for the promotion gates (spec 08)."""

from decimal import Decimal

import pytest

from algotrade.backtest.config import BacktestConfig
from algotrade.backtest.walk_forward import WalkForwardConfig, WalkForwardRunner
from algotrade.data.features import FeatureConfig
from algotrade.domain.errors import BacktestError
from tests.fakes import FakeDataFeed

from .test_runner import synthetic_bars


def make_config() -> BacktestConfig:
    return BacktestConfig(
        strategy_params={"fast_window": 3, "slow_window": 8},
        features=FeatureConfig(sma_windows=(3, 8), vol_window=3),
        trade_quantity=Decimal(10),
    )


class TestFolds:
    def test_rolling_folds_cover_the_period_without_overlap(self) -> None:
        bars = synthetic_bars(90)
        runner = WalkForwardRunner(FakeDataFeed(bars))

        result = runner.run(
            "sma_cross",
            "TEST",
            "2026-01-01",
            "2026-12-31",
            make_config(),
            WalkForwardConfig(train_bars=30, test_bars=20),
        )

        assert len(result.folds) == 3  # (90 - 30) // 20 full test windows
        for i, fold in enumerate(result.folds):
            assert fold.fold == i
            assert fold.train_end < fold.test_start
            assert fold.report.bars_used == 20
        # consecutive test windows are adjacent, not overlapping
        assert result.folds[0].test_end < result.folds[1].test_start

    def test_per_fold_reports_carry_full_metrics(self) -> None:
        bars = synthetic_bars(90)
        runner = WalkForwardRunner(FakeDataFeed(bars))
        result = runner.run(
            "sma_cross",
            "TEST",
            "2026-01-01",
            "2026-12-31",
            make_config(),
            WalkForwardConfig(train_bars=30, test_bars=20),
        )
        for fold in result.folds:
            assert fold.report.strategy_id == "sma_cross"
            assert fold.report.metrics.trade_count >= 0  # metrics object fully built

    def test_aggregates_match_fold_metrics(self) -> None:
        bars = synthetic_bars(90)
        runner = WalkForwardRunner(FakeDataFeed(bars))
        result = runner.run(
            "sma_cross",
            "TEST",
            "2026-01-01",
            "2026-12-31",
            make_config(),
            WalkForwardConfig(train_bars=30, test_bars=20),
        )
        sharpes = [f.report.metrics.sharpe for f in result.folds]
        positives = [f for f in result.folds if f.report.metrics.total_return > 0]
        assert result.oos_sharpe_mean == pytest.approx(sum(sharpes) / len(sharpes))
        assert result.positive_fold_fraction == pytest.approx(len(positives) / len(result.folds))


class TestValidation:
    def test_too_little_data_for_one_fold_raises(self) -> None:
        bars = synthetic_bars(30)
        runner = WalkForwardRunner(FakeDataFeed(bars))
        with pytest.raises(BacktestError, match="fold"):
            runner.run(
                "sma_cross",
                "TEST",
                "2026-01-01",
                "2026-12-31",
                make_config(),
                WalkForwardConfig(train_bars=25, test_bars=20),
            )
