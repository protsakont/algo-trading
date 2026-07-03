"""NautilusTrader adapter (spec 04) — the ONLY place engine types touch our
domain. Maps domain Bars/Strategy into an engine run and returns raw fills.

The bridge strategy replays the ORIGINAL domain bars for feature computation
(exact Decimals, no engine precision loss); the engine handles order routing
and fill simulation. Cost assumptions (slippage/commission) are applied later
in accounting, not here — declared in the report.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar as NautilusBar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.enums import OrderSide as NautilusOrderSide
from nautilus_trader.model.events import OrderDenied, OrderFilled, OrderRejected
from nautilus_trader.model.identifiers import TraderId, Venue
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.trading.strategy import Strategy as NautilusStrategy

from algotrade.backtest.accounting import FillRecord
from algotrade.domain.dto import Bar, Signal
from algotrade.domain.enums import OrderSide, SignalDirection
from algotrade.domain.errors import BacktestError
from algotrade.interfaces import FeatureStore, Strategy

_VENUE = Venue("BACKTEST")

_TIMEFRAME_TO_BAR_SPEC = {
    "1m": "1-MINUTE",
    "5m": "5-MINUTE",
    "15m": "15-MINUTE",
    "1h": "1-HOUR",
    "4h": "4-HOUR",
    "1d": "1-DAY",
}

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)

_TARGET_BY_DIRECTION = {
    SignalDirection.LONG: Decimal(1),
    SignalDirection.SHORT: Decimal(-1),
    SignalDirection.FLAT: Decimal(0),
}


def _bar_type(instrument: Equity, timeframe: str) -> BarType:
    spec = _TIMEFRAME_TO_BAR_SPEC.get(timeframe)
    if spec is None:
        raise BacktestError(
            f"unsupported timeframe {timeframe!r}; known: {sorted(_TIMEFRAME_TO_BAR_SPEC)}"
        )
    return BarType.from_str(f"{instrument.id}-{spec}-LAST-EXTERNAL")


def _to_nanos(bar: Bar) -> int:
    """Exact integer nanos — float .timestamp() round-trips lose ~100ns on
    microsecond-precision intraday timestamps."""
    return ((bar.timestamp - _EPOCH) // _MICROSECOND) * 1_000


def _from_nanos(nanos: int) -> datetime:
    return _EPOCH + timedelta(microseconds=nanos // 1_000)


def _to_nautilus_bars(bars: list[Bar], bar_type: BarType, instrument: Equity) -> list[NautilusBar]:
    return [
        NautilusBar(
            bar_type=bar_type,
            open=Price(float(b.open), instrument.price_precision),
            high=Price(float(b.high), instrument.price_precision),
            low=Price(float(b.low), instrument.price_precision),
            close=Price(float(b.close), instrument.price_precision),
            volume=Quantity(float(b.volume), instrument.size_precision),
            ts_event=_to_nanos(b),
            ts_init=_to_nanos(b),
        )
        for b in bars
    ]


class _BridgeConfig(StrategyConfig, frozen=True):
    bar_type: BarType


class _SignalBridge(NautilusStrategy):
    """Feeds domain bars through FeatureStore -> Strategy and turns signal
    direction into a target position of +/- trade_quantity (fixed sizing is a
    declared M3 assumption; real sizing is the risk module's job, spec 05).

    Execution model (declared in the report): market orders fill at the SAME
    bar's close with zero latency — optimistic but lookahead-free. When a
    strategy emits multiple signals per bar, only the LAST one is acted on."""

    def __init__(
        self,
        config: _BridgeConfig,
        domain_strategy: Strategy,
        feature_store: FeatureStore,
        source_bars: list[Bar],
        trade_quantity: Decimal,
    ) -> None:
        super().__init__(config)
        self._domain_strategy = domain_strategy
        self._feature_store = feature_store
        self._source_bars = source_bars
        self._trade_quantity = trade_quantity
        self._history: list[Bar] = []
        self._position = Decimal(0)
        self.fills: list[FillRecord] = []

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: NautilusBar) -> None:
        index = len(self._history)
        if index >= len(self._source_bars):
            raise BacktestError("engine emitted more bars than were provided")
        source = self._source_bars[index]
        if _to_nanos(source) != bar.ts_event:
            raise BacktestError(
                f"bar stream desynchronized at index {index}: "
                f"{source.timestamp.isoformat()} != ts_event {bar.ts_event}"
            )
        self._history.append(source)

        signals = self._domain_strategy.on_features(self._feature_store.compute(self._history))
        if not signals:
            return
        self._trade_towards(self._target_position(signals[-1]))

    def on_order_filled(self, event: OrderFilled) -> None:
        quantity = event.last_qty.as_decimal()
        is_buy = event.order_side == NautilusOrderSide.BUY
        self._position += quantity if is_buy else -quantity
        self.fills.append(
            FillRecord(
                timestamp=_from_nanos(event.ts_event),
                side=OrderSide.BUY if is_buy else OrderSide.SELL,
                quantity=quantity,
                price=event.last_px.as_decimal(),
            )
        )

    def on_order_rejected(self, event: OrderRejected) -> None:
        # In a backtest a rejection means the setup is wrong (sizing vs
        # balance, margin) — silently under-trading would corrupt the report.
        raise BacktestError(f"order rejected by simulated venue: {event}")

    def on_order_denied(self, event: OrderDenied) -> None:
        raise BacktestError(f"order denied pre-venue: {event}")

    def _target_position(self, signal: Signal) -> Decimal:
        return _TARGET_BY_DIRECTION[signal.direction] * self._trade_quantity

    def _trade_towards(self, target: Decimal) -> None:
        delta = target - self._position
        if not delta:
            return
        order = self.order_factory.market(
            instrument_id=self.config.bar_type.instrument_id,
            order_side=NautilusOrderSide.BUY if delta > 0 else NautilusOrderSide.SELL,
            quantity=Quantity(float(abs(delta)), 0),
        )
        self.submit_order(order)


def run_engine(
    bars: list[Bar],
    domain_strategy: Strategy,
    feature_store: FeatureStore,
    trade_quantity: Decimal,
    initial_cash: Decimal,
) -> list[FillRecord]:
    """Run one backtest and return raw engine fills in event order."""
    symbol = bars[0].symbol
    instrument = TestInstrumentProvider.equity(symbol=symbol, venue=_VENUE.value)
    bar_type = _bar_type(instrument, bars[0].timeframe)

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("BACKTEST-001"),
            logging=LoggingConfig(bypass_logging=True),
        )
    )
    try:
        engine.add_venue(
            venue=_VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=USD,
            starting_balances=[Money(float(initial_cash), USD)],
        )
        engine.add_instrument(instrument)
        engine.add_data(_to_nautilus_bars(bars, bar_type, instrument))
        bridge = _SignalBridge(
            config=_BridgeConfig(bar_type=bar_type),
            domain_strategy=domain_strategy,
            feature_store=feature_store,
            source_bars=bars,
            trade_quantity=trade_quantity,
        )
        engine.add_strategy(bridge)
        engine.run()
        return list(bridge.fills)
    except BacktestError:
        raise
    except Exception as exc:  # engine boundary: map everything to BacktestError
        raise BacktestError(f"nautilus engine failure: {exc}") from exc
    finally:
        engine.dispose()
