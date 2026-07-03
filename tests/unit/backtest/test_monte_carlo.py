"""Monte Carlo trade-order resampling (spec 04 P1): reshuffling the *order* of
the realized trades keeps the total P&L identical but changes the drawdown path,
so the spread of MaxDD across orderings measures how much the observed drawdown
was down to lucky sequencing. Seeded → reproducible."""

from decimal import Decimal

import pytest

from algotrade.backtest.monte_carlo import (
    MonteCarloDrawdown,
    _percentile,
    monte_carlo_drawdown,
)
from algotrade.domain.errors import BacktestError

START = Decimal("1000")
# Equity in order: 1000 -> 1100 -> 800 -> 850. Peak 1100, deepest = 1 - 800/1100.
PNLS = [Decimal("100"), Decimal("-300"), Decimal("50")]
OBSERVED_DD = 1 - 800 / 1100  # 0.27272...
WORST_DD = 1 - 700 / 1000  # -300 first, off the initial peak: 0.30


class TestObserved:
    def test_observed_drawdown_matches_in_order_sequence(self) -> None:
        result = monte_carlo_drawdown(PNLS, START, simulations=500, seed=1)
        assert result.observed_max_drawdown == pytest.approx(OBSERVED_DD)

    def test_result_carries_run_parameters(self) -> None:
        result = monte_carlo_drawdown(PNLS, START, simulations=321, seed=7)
        assert isinstance(result, MonteCarloDrawdown)
        assert result.simulations == 321
        assert result.seed == 7


class TestDistribution:
    def test_percentiles_are_monotonic(self) -> None:
        result = monte_carlo_drawdown(PNLS, START, simulations=1000, seed=3)
        assert (
            0.0
            <= result.median_max_drawdown
            <= result.p95_max_drawdown
            <= result.p99_max_drawdown
            <= result.worst_max_drawdown
        )
        # Mean is bounded by the range but need not straddle the median
        # (the MaxDD distribution is skewed).
        assert 0.0 <= result.mean_max_drawdown <= result.worst_max_drawdown

    def test_worst_ordering_is_found_with_enough_simulations(self) -> None:
        # Only 3 trades (6 orderings); 1000 draws hit the worst one.
        result = monte_carlo_drawdown(PNLS, START, simulations=1000, seed=3)
        assert result.worst_max_drawdown == pytest.approx(WORST_DD)
        assert result.worst_max_drawdown >= result.observed_max_drawdown

    def test_single_simulation_collapses_to_one_sample(self) -> None:
        result = monte_carlo_drawdown(PNLS, START, simulations=1, seed=0)
        assert result.median_max_drawdown == result.worst_max_drawdown
        assert result.mean_max_drawdown == result.worst_max_drawdown

    def test_all_winning_trades_never_draw_down(self) -> None:
        gains = [Decimal("10"), Decimal("20"), Decimal("30")]
        result = monte_carlo_drawdown(gains, START, simulations=200, seed=5)
        assert result.worst_max_drawdown == 0.0
        assert result.mean_max_drawdown == 0.0

    def test_ruinous_reordering_exceeds_one(self) -> None:
        # A loss larger than starting equity: some orderings wipe the account,
        # surfacing as a drawdown fraction above 1.0 (honest ruin signal).
        pnls = [Decimal("200"), Decimal("-1200"), Decimal("200")]
        result = monte_carlo_drawdown(pnls, START, simulations=1000, seed=2)
        assert result.worst_max_drawdown > 1.0


class TestDeterminism:
    def test_same_seed_same_result(self) -> None:
        a = monte_carlo_drawdown(PNLS, START, simulations=500, seed=42)
        b = monte_carlo_drawdown(PNLS, START, simulations=500, seed=42)
        assert a == b

    def test_different_seed_generally_differs(self) -> None:
        a = monte_carlo_drawdown(PNLS, START, simulations=500, seed=1)
        b = monte_carlo_drawdown(PNLS, START, simulations=500, seed=2)
        # Mean over a different sample of orderings should not coincide exactly.
        assert a.mean_max_drawdown != b.mean_max_drawdown


class TestPercentile:
    """Pin the linear-interpolation percentile (numpy type-7 / 'linear') against
    hand-computed values so an off-by-one in the rank can't slip through."""

    def test_interpolates_between_ranks(self) -> None:
        data = [0.0, 1.0, 2.0, 3.0, 4.0]  # already sorted
        assert _percentile(data, 50.0) == pytest.approx(2.0)  # rank 2.0
        assert _percentile(data, 95.0) == pytest.approx(3.8)  # rank 3.8
        assert _percentile(data, 99.0) == pytest.approx(3.96)  # rank 3.96

    def test_endpoints(self) -> None:
        data = [10.0, 20.0, 30.0, 40.0]
        assert _percentile(data, 0.0) == pytest.approx(10.0)
        assert _percentile(data, 100.0) == pytest.approx(40.0)

    def test_single_value(self) -> None:
        assert _percentile([7.0], 95.0) == 7.0


class TestGuards:
    def test_fewer_than_two_trades_is_rejected(self) -> None:
        with pytest.raises(BacktestError, match="at least 2 trades"):
            monte_carlo_drawdown([Decimal("10")], START, simulations=100, seed=0)

    def test_non_positive_simulations_is_rejected(self) -> None:
        with pytest.raises(BacktestError, match="simulations"):
            monte_carlo_drawdown(PNLS, START, simulations=0, seed=0)

    def test_non_positive_starting_equity_is_rejected(self) -> None:
        with pytest.raises(BacktestError, match="starting equity"):
            monte_carlo_drawdown(PNLS, Decimal("0"), simulations=100, seed=0)
