"""Core Protocols exactly as specified in specs/01-architecture.md.

Changing any signature here after another module implements it is an
escalation event (specs/09) — ask the human first.
"""

from decimal import Decimal
from typing import Protocol, runtime_checkable

from algotrade.domain.dto import (
    Bar,
    FeatureSet,
    Order,
    OrderResult,
    Position,
    RiskVerdict,
    Signal,
)


@runtime_checkable
class DataFeed(Protocol):
    """Single source of market data. No other module may call a vendor directly."""

    def get_bars(self, symbol: str, start: str, end: str, timeframe: str) -> list[Bar]: ...


@runtime_checkable
class FeatureStore(Protocol):
    def compute(self, bars: list[Bar]) -> FeatureSet: ...


@runtime_checkable
class Strategy(Protocol):
    """Every strategy implements only this — stateless per call, deterministic
    for identical features (spec 03)."""

    def on_features(self, features: FeatureSet) -> list[Signal]: ...


@runtime_checkable
class RiskChecker(Protocol):
    """Always returns a verdict — never throws to reject (spec 05)."""

    def check(self, order: Order, positions: list[Position]) -> RiskVerdict: ...


@runtime_checkable
class PositionSizer(Protocol):
    def size(self, signal: Signal, equity: Decimal, positions: list[Position]) -> Decimal: ...


@runtime_checkable
class BrokerGateway(Protocol):
    def submit(self, order: Order) -> OrderResult: ...

    def cancel(self, order_id: str) -> OrderResult: ...

    def positions(self) -> list[Position]: ...


@runtime_checkable
class AlertSink(Protocol):
    def send(self, severity: str, message: str) -> None: ...
