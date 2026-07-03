"""Parameter-sensitivity sweep (spec 04 P1, engine-agnostic core).

Runs a caller-provided evaluation over a 2-D parameter grid and returns the
metric surface a heatmap renders from, plus the best cell. The evaluator is
injected — a fast VectorBT triage or the real BacktestRunner both plug in — so
this core carries no engine dependency (see D-012)."""

import pytest
from pydantic import ValidationError

from algotrade.backtest.sweep import SensitivitySurface, parameter_sweep
from algotrade.domain.errors import BacktestError


class TestSurface:
    def test_grid_is_row_major_over_y_then_x(self) -> None:
        surface = parameter_sweep(
            "fast",
            [1.0, 2.0, 3.0],
            "slow",
            [10.0, 20.0],
            metric="sharpe",
            evaluate=lambda fast, slow: fast * 100 + slow,
        )
        assert isinstance(surface, SensitivitySurface)
        assert surface.x_values == (1.0, 2.0, 3.0)
        assert surface.y_values == (10.0, 20.0)
        # grid[y_index][x_index]
        assert surface.grid == (
            (110.0, 210.0, 310.0),  # slow=10
            (120.0, 220.0, 320.0),  # slow=20
        )

    def test_labels_and_metric_preserved(self) -> None:
        surface = parameter_sweep(
            "fast", [1.0], "slow", [2.0], metric="max_drawdown", evaluate=lambda a, b: 0.5
        )
        assert surface.x_param == "fast"
        assert surface.y_param == "slow"
        assert surface.metric == "max_drawdown"

    def test_single_cell(self) -> None:
        surface = parameter_sweep(
            "a", [1.0], "b", [2.0], metric="sharpe", evaluate=lambda a, b: 7.0
        )
        assert surface.grid == ((7.0,),)
        assert (surface.best_x, surface.best_y, surface.best_value) == (1.0, 2.0, 7.0)


class TestBestCell:
    def test_maximize_picks_highest(self) -> None:
        surface = parameter_sweep(
            "fast",
            [1.0, 2.0],
            "slow",
            [10.0, 20.0],
            metric="sharpe",
            evaluate=lambda fast, slow: fast * slow,  # max at (2, 20) = 40
        )
        assert (surface.best_x, surface.best_y, surface.best_value) == (2.0, 20.0, 40.0)

    def test_minimize_picks_lowest_for_drawdown(self) -> None:
        surface = parameter_sweep(
            "fast",
            [1.0, 2.0],
            "slow",
            [10.0, 20.0],
            metric="max_drawdown",
            evaluate=lambda fast, slow: fast * slow,  # min at (1, 10) = 10
            maximize=False,
        )
        assert (surface.best_x, surface.best_y, surface.best_value) == (1.0, 10.0, 10.0)

    def test_ties_resolve_to_first_cell_row_major(self) -> None:
        surface = parameter_sweep(
            "fast",
            [1.0, 2.0],
            "slow",
            [10.0, 20.0],
            metric="sharpe",
            evaluate=lambda fast, slow: 5.0,  # all equal
        )
        assert (surface.best_x, surface.best_y) == (1.0, 10.0)

    def test_ties_resolve_to_first_cell_when_minimizing(self) -> None:
        surface = parameter_sweep(
            "fast",
            [1.0, 2.0],
            "slow",
            [10.0, 20.0],
            metric="max_drawdown",
            evaluate=lambda fast, slow: 5.0,
            maximize=False,
        )
        assert (surface.best_x, surface.best_y) == (1.0, 10.0)


class TestDeterminism:
    def test_pure_evaluator_is_reproducible(self) -> None:
        args = ("fast", [1.0, 2.0], "slow", [3.0, 4.0])
        a = parameter_sweep(*args, metric="sharpe", evaluate=lambda x, y: x - y)
        b = parameter_sweep(*args, metric="sharpe", evaluate=lambda x, y: x - y)
        assert a == b


class TestGuards:
    def test_empty_x_axis_is_rejected(self) -> None:
        with pytest.raises(BacktestError, match="x axis"):
            parameter_sweep("fast", [], "slow", [1.0], metric="sharpe", evaluate=lambda a, b: 0.0)

    def test_empty_y_axis_is_rejected(self) -> None:
        with pytest.raises(BacktestError, match="y axis"):
            parameter_sweep("fast", [1.0], "slow", [], metric="sharpe", evaluate=lambda a, b: 0.0)

    def test_non_finite_metric_is_rejected(self) -> None:
        """A NaN (e.g. undefined Sharpe from a zero-trade combo) must not be
        silently ranked best — it corrupts the overfitting read."""
        with pytest.raises(BacktestError, match=r"not finite at \(x=1.0, y=2.0\)"):
            parameter_sweep(
                "fast",
                [1.0],
                "slow",
                [2.0],
                metric="sharpe",
                evaluate=lambda a, b: float("nan"),
            )

    def test_evaluator_error_is_wrapped_with_coordinates(self) -> None:
        def boom(x: float, y: float) -> float:
            raise ValueError("engine blew up")

        with pytest.raises(BacktestError, match=r"raised at \(x=1.0, y=2.0\)"):
            parameter_sweep("fast", [1.0], "slow", [2.0], metric="sharpe", evaluate=boom)

    def test_backtest_error_from_evaluator_propagates_unwrapped(self) -> None:
        """An evaluator that already raises BacktestError (e.g. the runner) keeps
        its own message — no double-wrapping."""

        def failing(x: float, y: float) -> float:
            raise BacktestError("curve needs at least 2 points")

        with pytest.raises(BacktestError, match="at least 2 points"):
            parameter_sweep("fast", [1.0], "slow", [2.0], metric="sharpe", evaluate=failing)


class TestSurfaceInvariant:
    def test_grid_shape_must_match_axes(self) -> None:
        with pytest.raises(ValidationError):
            SensitivitySurface(
                x_param="a",
                y_param="b",
                x_values=(1.0, 2.0),
                y_values=(1.0,),
                metric="sharpe",
                grid=((1.0,),),  # 1 column, but x axis has 2
                best_x=1.0,
                best_y=1.0,
                best_value=1.0,
            )

    def test_grid_row_count_must_match_y_axis(self) -> None:
        with pytest.raises(ValidationError):
            SensitivitySurface(
                x_param="a",
                y_param="b",
                x_values=(1.0,),
                y_values=(1.0, 2.0),  # 2 rows expected
                metric="sharpe",
                grid=((1.0,),),  # only 1 row
                best_x=1.0,
                best_y=1.0,
                best_value=1.0,
            )

    def test_best_cell_must_lie_on_axes(self) -> None:
        with pytest.raises(ValidationError):
            SensitivitySurface(
                x_param="a",
                y_param="b",
                x_values=(1.0,),
                y_values=(1.0,),
                metric="sharpe",
                grid=((1.0,),),
                best_x=9.0,
                best_y=1.0,
                best_value=1.0,  # 9.0 not on x axis
            )
