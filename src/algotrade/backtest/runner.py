"""BacktestRunner (spec 04): (strategy_id, symbol, period, config) -> report.

Engine fills and domain bars are merged into a cost-adjusted equity ledger
OUTSIDE the engine, so results are deterministic regardless of engine event
ordering, and assumptions live in exactly one place (the config)."""

from collections.abc import Callable, Mapping

from algotrade.backtest.accounting import EquityPoint, FillRecord, Ledger
from algotrade.backtest.config import BacktestConfig
from algotrade.backtest.metrics import compute_metrics
from algotrade.backtest.nautilus_adapter import run_engine
from algotrade.backtest.report import BacktestReport
from algotrade.data.features import FeatureConfig, PolarsFeatureStore
from algotrade.domain.dto import Bar
from algotrade.domain.errors import BacktestError
from algotrade.interfaces import DataFeed, FeatureStore, Strategy
from algotrade.strategy import build_strategy

StrategyBuilder = Callable[[str, Mapping[str, object]], Strategy]
FeatureStoreFactory = Callable[[FeatureConfig], FeatureStore]


def _build_equity_curve(
    bars: list[Bar], fills: list[FillRecord], ledger: Ledger
) -> list[EquityPoint]:
    """Apply fills in timestamp order, marking to market at every bar close."""
    pending = sorted(fills, key=lambda f: f.timestamp)
    cursor = 0
    curve: list[EquityPoint] = []
    for bar in bars:
        while cursor < len(pending) and pending[cursor].timestamp <= bar.timestamp:
            ledger.apply_fill(pending[cursor])
            cursor += 1
        curve.append(ledger.mark(bar.timestamp, bar.close))
    if cursor != len(pending):
        raise BacktestError(
            f"{len(pending) - cursor} fill(s) timestamped after the final bar - "
            "engine and data are out of sync"
        )
    return curve


class BacktestRunner:
    """Defaults wire the registry loader and polars feature store; the
    composition root (or a test) can inject alternatives."""

    def __init__(
        self,
        feed: DataFeed,
        strategy_builder: StrategyBuilder = build_strategy,
        feature_store_factory: FeatureStoreFactory = PolarsFeatureStore,
    ) -> None:
        self._feed = feed
        self._build_strategy = strategy_builder
        self._feature_store_factory = feature_store_factory

    def run(
        self, strategy_id: str, symbol: str, start: str, end: str, config: BacktestConfig
    ) -> BacktestReport:
        bars = self._feed.get_bars(symbol, start, end, config.timeframe)
        if not bars:
            raise BacktestError(
                f"no bars for {symbol}/{config.timeframe} in [{start}, {end}] - nothing to test"
            )
        strategy = self._build_strategy(strategy_id, config.strategy_params)
        feature_store = self._feature_store_factory(config.features)

        fills = run_engine(
            bars=bars,
            domain_strategy=strategy,
            feature_store=feature_store,
            trade_quantity=config.trade_quantity,
            initial_cash=config.initial_cash,
        )

        ledger = Ledger(
            initial_cash=config.initial_cash,
            slippage_bps=config.slippage_bps,
            commission_bps=config.commission_bps,
        )
        curve = _build_equity_curve(bars, fills, ledger)
        metrics = compute_metrics(
            curve,
            round_trips=ledger.round_trips,
            traded_notional=ledger.traded_notional,
            periods_per_year=config.periods_per_year,
        )
        return BacktestReport(
            strategy_id=strategy_id,
            symbol=symbol,
            start=bars[0].timestamp,
            end=bars[-1].timestamp,
            config=config,
            metrics=metrics,
            bars_used=len(bars),
        )
