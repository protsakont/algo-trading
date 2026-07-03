"""BacktestRunner end-to-end over the real NautilusTrader engine (spec 04):
baseline SMA cross on synthetic fixture bars — completes, produces a full
report, and is reproducible (same config + data + seed = identical metrics)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from algotrade.backtest.config import BacktestConfig
from algotrade.backtest.report import BacktestReport
from algotrade.backtest.runner import BacktestRunner
from algotrade.data.features import FeatureConfig
from algotrade.domain.dto import Bar
from algotrade.domain.errors import BacktestError, ConfigError
from tests.fakes import FakeDataFeed

T0 = datetime(2026, 1, 5, 21, 0, tzinfo=UTC)


def synthetic_bars(count: int = 90) -> list[Bar]:
    """Deterministic up-then-down trend so a 5/15 SMA cross trades both ways."""
    bars = []
    for i in range(count):
        mid = 100.0 + (i * 0.8 if i < count // 2 else (count // 2) * 0.8 - (i - count // 2) * 0.9)
        close = round(mid, 2)
        bars.append(
            Bar(
                symbol="TEST",
                timestamp=T0 + timedelta(days=i),
                timeframe="1d",
                open=Decimal(str(round(mid - 0.2, 2))),
                high=Decimal(str(round(mid + 0.6, 2))),
                low=Decimal(str(round(mid - 0.6, 2))),
                close=Decimal(str(close)),
                volume=Decimal("10000"),
            )
        )
    return bars


def make_config() -> BacktestConfig:
    return BacktestConfig(
        strategy_params={"fast_window": 5, "slow_window": 15},
        features=FeatureConfig(sma_windows=(5, 15), vol_window=5),
        trade_quantity=Decimal(10),
    )


@pytest.fixture(scope="module")
def completed_report() -> BacktestReport:
    """One engine run shared by the assertion tests (engine runs are the slow
    part; assertions are read-only on a frozen report)."""
    runner = BacktestRunner(FakeDataFeed(synthetic_bars()))
    return runner.run("sma_cross", "TEST", "2026-01-01", "2026-12-31", make_config())


class TestEndToEnd:
    def test_report_identity_and_span(self, completed_report: BacktestReport) -> None:
        report = completed_report
        assert report.strategy_id == "sma_cross"
        assert report.symbol == "TEST"
        assert report.bars_used == 90
        assert report.start == T0
        assert report.end == T0 + timedelta(days=89)

    def test_strategy_actually_traded(self, completed_report: BacktestReport) -> None:
        assert completed_report.metrics.trade_count >= 1
        assert completed_report.metrics.turnover > 0
        assert completed_report.metrics.exposure > 0

    def test_all_metrics_are_finite(self, completed_report: BacktestReport) -> None:
        import math

        for name, value in completed_report.metrics.model_dump().items():
            assert not math.isnan(float(value)), f"{name} is NaN"
            assert math.isfinite(float(value)), f"{name} is not finite"


class TestReproducibility:
    def test_same_config_data_seed_gives_identical_report(self) -> None:
        """Spec 04 P0: same config + data + seed = identical metrics."""
        bars = synthetic_bars()
        first = BacktestRunner(FakeDataFeed(bars)).run(
            "sma_cross", "TEST", "2026-01-01", "2026-12-31", make_config()
        )
        second = BacktestRunner(FakeDataFeed(bars)).run(
            "sma_cross", "TEST", "2026-01-01", "2026-12-31", make_config()
        )
        assert first.metrics == second.metrics
        assert first == second


class TestFailures:
    def test_no_bars_raises_backtest_error(self) -> None:
        runner = BacktestRunner(FakeDataFeed([]))
        with pytest.raises(BacktestError, match="no bars"):
            runner.run("sma_cross", "TEST", "2026-01-01", "2026-12-31", make_config())

    def test_unknown_strategy_raises_config_error(self) -> None:
        runner = BacktestRunner(FakeDataFeed(synthetic_bars(20)))
        with pytest.raises(ConfigError, match="unknown strategy"):
            runner.run("nope", "TEST", "2026-01-01", "2026-12-31", make_config())

    def test_fractional_trade_quantity_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="whole number"):
            BacktestConfig(trade_quantity=Decimal("2.5"))

    def test_fill_after_final_bar_raises(self) -> None:
        from datetime import timedelta as _td

        from algotrade.backtest.accounting import FillRecord, Ledger
        from algotrade.backtest.runner import _build_equity_curve
        from algotrade.domain.enums import OrderSide

        bars = synthetic_bars(5)
        stray = FillRecord(
            timestamp=bars[-1].timestamp + _td(days=1),
            side=OrderSide.BUY,
            quantity=Decimal(1),
            price=Decimal(100),
        )
        ledger = Ledger(Decimal(1000), Decimal(0), Decimal(0))
        with pytest.raises(BacktestError, match="after the final bar"):
            _build_equity_curve(bars, [stray], ledger)

    def test_unsupported_timeframe_raises_backtest_error(self) -> None:
        bars = [b.model_copy(update={"timeframe": "7w"}) for b in synthetic_bars(20)]
        runner = BacktestRunner(FakeDataFeed(bars))
        with pytest.raises(BacktestError, match="timeframe"):
            runner.run(
                "sma_cross",
                "TEST",
                "2026-01-01",
                "2026-12-31",
                BacktestConfig(
                    timeframe="7w",
                    strategy_params={"fast_window": 5, "slow_window": 15},
                    features=FeatureConfig(sma_windows=(5, 15), vol_window=5),
                ),
            )
