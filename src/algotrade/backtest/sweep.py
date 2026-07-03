"""Parameter-sensitivity sweep (spec 04 P1).

Evaluates a metric across a 2-D grid of two strategy parameters and returns the
surface a heatmap is drawn from, plus the best cell. Sensitivity analysis is a
guard against overfitting: a good result sitting on an isolated spike (neighbours
far worse) is fragile; a broad plateau is trustworthy. Reading that off the grid
is the caller's job — this returns the surface honestly.

The evaluator is injected as ``evaluate(x_value, y_value) -> metric``, so the
core is engine-agnostic: a fast VectorBT triage or the real ``BacktestRunner``
plug in the same way (see D-012). A pure evaluator makes the sweep reproducible.
"""

import math
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict, model_validator

from algotrade.domain.errors import BacktestError


class SensitivitySurface(BaseModel):
    """Heatmap-ready metric surface. ``grid[y_index][x_index]`` is the metric at
    ``(x_values[x_index], y_values[y_index])`` (row-major over y then x)."""

    model_config = ConfigDict(frozen=True)

    x_param: str
    y_param: str
    x_values: tuple[float, ...]
    y_values: tuple[float, ...]
    metric: str
    grid: tuple[tuple[float, ...], ...]
    best_x: float
    best_y: float
    best_value: float

    @model_validator(mode="after")
    def _check_shape(self) -> "SensitivitySurface":
        """A surface whose grid does not match its axes renders a wrong heatmap —
        make that unrepresentable (D-003), not just avoided by convention."""
        if len(self.grid) != len(self.y_values):
            raise ValueError(f"grid has {len(self.grid)} rows, expected {len(self.y_values)}")
        if any(len(row) != len(self.x_values) for row in self.grid):
            raise ValueError(f"every grid row must have {len(self.x_values)} columns")
        if self.best_x not in self.x_values or self.best_y not in self.y_values:
            raise ValueError("best cell coordinates must lie on the axes")
        return self


def parameter_sweep(
    x_param: str,
    x_values: Sequence[float],
    y_param: str,
    y_values: Sequence[float],
    *,
    metric: str,
    evaluate: Callable[[float, float], float],
    maximize: bool = True,
) -> SensitivitySurface:
    """Sweep ``evaluate`` over the ``x_values`` by ``y_values`` grid.

    ``maximize`` selects the best cell: True for reward-like metrics (Sharpe),
    False for cost-like metrics (max drawdown). Ties resolve to the first cell
    scanned (row-major).
    """
    if not x_values:
        raise BacktestError(f"x axis {x_param!r} is empty")
    if not y_values:
        raise BacktestError(f"y axis {y_param!r} is empty")

    xs = tuple(float(x) for x in x_values)
    ys = tuple(float(y) for y in y_values)

    grid = tuple(tuple(_evaluate_cell(evaluate, x, y, metric) for x in xs) for y in ys)

    best_y_index, best_x_index = _best_cell(grid, maximize)
    return SensitivitySurface(
        x_param=x_param,
        y_param=y_param,
        x_values=xs,
        y_values=ys,
        metric=metric,
        grid=grid,
        best_x=xs[best_x_index],
        best_y=ys[best_y_index],
        best_value=grid[best_y_index][best_x_index],
    )


def _evaluate_cell(
    evaluate: Callable[[float, float], float], x: float, y: float, metric: str
) -> float:
    """Run one injected evaluation at the boundary: map any engine/user
    exception to ``BacktestError`` naming the cell (rule 5 — no raw exceptions
    cross the boundary, and a coordinate makes a failed sweep debuggable), and
    reject a non-finite metric so a NaN cannot masquerade as the best cell."""
    try:
        value = evaluate(x, y)
    except BacktestError:
        raise
    except Exception as exc:  # injected callable may raise anything — this is the boundary
        raise BacktestError(f"evaluate raised at (x={x}, y={y}): {exc}") from exc
    if not math.isfinite(value):
        raise BacktestError(f"metric {metric!r} is not finite at (x={x}, y={y})")
    return value


def _best_cell(grid: Sequence[Sequence[float]], maximize: bool) -> tuple[int, int]:
    """(y_index, x_index) of the best metric — argmax, or argmin when
    ``maximize`` is False. First cell wins ties (row-major scan)."""
    best_y_index = 0
    best_x_index = 0
    best = grid[0][0]
    for y_index, row in enumerate(grid):
        for x_index, value in enumerate(row):
            if (value > best) if maximize else (value < best):
                best, best_y_index, best_x_index = value, y_index, x_index
    return best_y_index, best_x_index
