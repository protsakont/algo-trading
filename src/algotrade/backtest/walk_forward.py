"""Walk-forward validation (spec 04): rolling train/test folds with one
backtest report per test fold.

v1 baseline strategies have fixed params, so the train window defines the
fold geometry but no fitting happens yet — parameter optimization per fold
arrives with the research layer. Each test fold runs standalone, so feature
warmup happens inside the fold (declared limitation)."""

from datetime import datetime
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field

from algotrade.backtest.config import BacktestConfig
from algotrade.backtest.report import BacktestReport
from algotrade.backtest.runner import BacktestRunner
from algotrade.domain.dto import Bar
from algotrade.domain.errors import BacktestError
from algotrade.interfaces import DataFeed


class WalkForwardConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    train_bars: int = Field(gt=0)
    test_bars: int = Field(gt=1)


class FoldReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    fold: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    report: BacktestReport


class WalkForwardReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    symbol: str
    folds: tuple[FoldReport, ...]
    oos_sharpe_mean: float
    positive_fold_fraction: float


class WalkForwardRunner:
    """One feed serves BOTH fold-window derivation and the fold backtests, so
    the two can never silently diverge."""

    def __init__(self, feed: DataFeed, runner: BacktestRunner | None = None) -> None:
        self._feed = feed
        self._runner = runner if runner is not None else BacktestRunner(feed)

    def run(
        self,
        strategy_id: str,
        symbol: str,
        start: str,
        end: str,
        config: BacktestConfig,
        walk_forward: WalkForwardConfig,
    ) -> WalkForwardReport:
        bars = self._feed.get_bars(symbol, start, end, config.timeframe)
        windows = self._fold_windows(bars, walk_forward)

        folds: list[FoldReport] = []
        for fold_index, (train, test) in enumerate(windows):
            report = self._runner.run(
                strategy_id,
                symbol,
                test[0].timestamp.isoformat(),
                test[-1].timestamp.isoformat(),
                config,
            )
            folds.append(
                FoldReport(
                    fold=fold_index,
                    train_start=train[0].timestamp,
                    train_end=train[-1].timestamp,
                    test_start=test[0].timestamp,
                    test_end=test[-1].timestamp,
                    report=report,
                )
            )

        sharpes = [f.report.metrics.sharpe for f in folds]
        positive = sum(1 for f in folds if f.report.metrics.total_return > 0)
        return WalkForwardReport(
            strategy_id=strategy_id,
            symbol=symbol,
            folds=tuple(folds),
            oos_sharpe_mean=fmean(sharpes),
            positive_fold_fraction=positive / len(folds),
        )

    @staticmethod
    def _fold_windows(
        bars: list[Bar], walk_forward: WalkForwardConfig
    ) -> list[tuple[list[Bar], list[Bar]]]:
        span = walk_forward.train_bars + walk_forward.test_bars
        if len(bars) < span:
            raise BacktestError(
                f"{len(bars)} bars cannot fit one walk-forward fold "
                f"(train {walk_forward.train_bars} + test {walk_forward.test_bars})"
            )
        windows: list[tuple[list[Bar], list[Bar]]] = []
        offset = 0
        while offset + span <= len(bars):
            train = bars[offset : offset + walk_forward.train_bars]
            test = bars[offset + walk_forward.train_bars : offset + span]
            windows.append((train, test))
            offset += walk_forward.test_bars
        return windows
