"""Backtest metrics (spec 04): every metric hand-verified on tiny series."""

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from algotrade.backtest.accounting import EquityPoint, RoundTrip
from algotrade.backtest.metrics import compute_metrics

T0 = datetime(2026, 1, 5, tzinfo=UTC)


def make_curve(values: list[str], positions: list[str] | None = None) -> list[EquityPoint]:
    positions = positions or ["0"] * len(values)
    return [
        EquityPoint(
            timestamp=T0 + timedelta(days=i),
            equity=Decimal(v),
            position=Decimal(p),
        )
        for i, (v, p) in enumerate(zip(values, positions, strict=True))
    ]


def make_trip(pnl: str) -> RoundTrip:
    return RoundTrip(
        opened_at=T0,
        closed_at=T0 + timedelta(days=1),
        quantity=Decimal("10"),
        pnl=Decimal(pnl),
    )


class TestReturns:
    def test_total_return(self) -> None:
        metrics = compute_metrics(
            make_curve(["100", "110", "121"]),
            round_trips=[],
            traded_notional=Decimal("0"),
            periods_per_year=252,
        )
        assert metrics.total_return == pytest.approx(0.21)

    def test_cagr_annualizes_by_periods(self) -> None:
        # 2 periods at 252/yr: (1.21)^(252/2) - 1
        metrics = compute_metrics(
            make_curve(["100", "110", "121"]),
            round_trips=[],
            traded_notional=Decimal("0"),
            periods_per_year=252,
        )
        assert metrics.cagr == pytest.approx(1.21 ** (252 / 2) - 1)

    def test_flat_curve_is_all_zeros(self) -> None:
        metrics = compute_metrics(
            make_curve(["100", "100", "100"]),
            round_trips=[],
            traded_notional=Decimal("0"),
            periods_per_year=252,
        )
        assert metrics.total_return == 0.0
        assert metrics.sharpe == 0.0
        assert metrics.max_drawdown == 0.0


class TestRiskRatios:
    def test_sharpe_matches_hand_computation(self) -> None:
        # returns: +10%, -5%  -> mean=0.025, pstdev=0.075
        metrics = compute_metrics(
            make_curve(["100", "110", "104.5"]),
            round_trips=[],
            traded_notional=Decimal("0"),
            periods_per_year=252,
        )
        expected = (0.025 / 0.075) * math.sqrt(252)
        assert metrics.sharpe == pytest.approx(expected, rel=1e-9)

    def test_sortino_uses_downside_deviation_only(self) -> None:
        # returns: +10%, -5%; downside dev = sqrt(mean([0, 0.05^2])) over n=2
        metrics = compute_metrics(
            make_curve(["100", "110", "104.5"]),
            round_trips=[],
            traded_notional=Decimal("0"),
            periods_per_year=252,
        )
        downside = math.sqrt((0.0**2 + 0.05**2) / 2)
        expected = (0.025 / downside) * math.sqrt(252)
        assert metrics.sortino == pytest.approx(expected, rel=1e-9)

    def test_all_positive_returns_give_zero_division_safe_sortino(self) -> None:
        metrics = compute_metrics(
            make_curve(["100", "101", "102"]),
            round_trips=[],
            traded_notional=Decimal("0"),
            periods_per_year=252,
        )
        assert metrics.sortino == 0.0  # no downside observed -> undefined -> 0


class TestDrawdown:
    def test_max_drawdown_from_peak(self) -> None:
        metrics = compute_metrics(
            make_curve(["100", "120", "90", "110"]),
            round_trips=[],
            traded_notional=Decimal("0"),
            periods_per_year=252,
        )
        assert metrics.max_drawdown == pytest.approx(0.25)  # 120 -> 90


class TestTradeStats:
    def test_win_rate_and_trade_count(self) -> None:
        trips = [make_trip("50"), make_trip("-20"), make_trip("10")]
        metrics = compute_metrics(
            make_curve(["100", "101"]),
            round_trips=trips,
            traded_notional=Decimal("0"),
            periods_per_year=252,
        )
        assert metrics.trade_count == 3
        assert metrics.win_rate == pytest.approx(2 / 3)

    def test_exposure_is_fraction_of_bars_in_market(self) -> None:
        metrics = compute_metrics(
            make_curve(["100", "100", "100", "100"], positions=["0", "10", "10", "0"]),
            round_trips=[],
            traded_notional=Decimal("0"),
            periods_per_year=252,
        )
        assert metrics.exposure == pytest.approx(0.5)

    def test_turnover_relative_to_average_equity(self) -> None:
        metrics = compute_metrics(
            make_curve(["100", "100"]),
            round_trips=[],
            traded_notional=Decimal("50"),
            periods_per_year=252,
        )
        assert metrics.turnover == pytest.approx(0.5)


class TestNumericSafety:
    def test_extreme_short_series_cagr_stays_finite(self) -> None:
        metrics = compute_metrics(
            make_curve(["100", "20000"]),
            round_trips=[],
            traded_notional=Decimal("0"),
            periods_per_year=252,
        )
        assert math.isfinite(metrics.cagr)

    def test_non_positive_equity_mid_curve_is_rejected(self) -> None:
        from algotrade.domain.errors import BacktestError

        with pytest.raises(BacktestError, match="non-positive"):
            compute_metrics(
                make_curve(["100", "-5", "50"]),
                round_trips=[],
                traded_notional=Decimal("0"),
                periods_per_year=252,
            )


class TestDegenerate:
    def test_fewer_than_two_points_is_rejected(self) -> None:
        from algotrade.domain.errors import BacktestError

        with pytest.raises(BacktestError, match="equity curve"):
            compute_metrics(
                make_curve(["100"]),
                round_trips=[],
                traded_notional=Decimal("0"),
                periods_per_year=252,
            )
