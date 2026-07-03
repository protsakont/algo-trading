"""Central in-memory fakes implementing every core Protocol (spec 01).

Tests inject these directly — the composition root is never involved.
"""

from datetime import UTC, datetime
from decimal import Decimal

from algotrade.domain.dto import (
    Bar,
    FeatureSet,
    Order,
    OrderResult,
    Position,
    RiskVerdict,
    Signal,
)
from algotrade.domain.enums import OrderStatus, SignalDirection


class FakeDataFeed:
    """Honors the DataFeed contract like ParquetDataFeed: closed [start, end]
    interval, date-only strings read as UTC midnight, sorted output."""

    def __init__(self, bars: list[Bar] | None = None) -> None:
        self._bars = bars or []

    def get_bars(self, symbol: str, start: str, end: str, timeframe: str) -> list[Bar]:
        start_ts = self._bound(start)
        end_ts = self._bound(end)
        matching = [
            b
            for b in self._bars
            if b.symbol == symbol and b.timeframe == timeframe and start_ts <= b.timestamp <= end_ts
        ]
        return sorted(matching, key=lambda b: b.timestamp)

    @staticmethod
    def _bound(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class FakeFeatureStore:
    def compute(self, bars: list[Bar]) -> FeatureSet:
        last = bars[-1]
        return FeatureSet(
            symbol=last.symbol,
            timestamp=last.timestamp,
            features={"close": float(last.close)},
        )


class AlwaysFlatStrategy:
    def on_features(self, features: FeatureSet) -> list[Signal]:
        return [
            Signal(
                strategy_id="always_flat",
                symbol=features.symbol,
                direction=SignalDirection.FLAT,
                strength=0.0,
                timestamp=features.timestamp,
            )
        ]


class ApproveAllRiskChecker:
    def check(self, order: Order, positions: list[Position]) -> RiskVerdict:
        return RiskVerdict(approved=True, reason="fake: approve all", check_name="ApproveAll")


class RejectAllRiskChecker:
    def check(self, order: Order, positions: list[Position]) -> RiskVerdict:
        return RiskVerdict(approved=False, reason="fake: reject all", check_name="RejectAll")


class FixedFractionSizer:
    def size(self, signal: Signal, equity: Decimal, positions: list[Position]) -> Decimal:
        return equity * Decimal("0.01")


class RecordingBrokerGateway:
    """Records submissions; never touches a network."""

    def __init__(self) -> None:
        self.submitted: list[Order] = []
        self.cancelled: list[str] = []

    def submit(self, order: Order) -> OrderResult:
        self.submitted.append(order)
        return OrderResult(client_order_id=order.client_order_id, status=OrderStatus.SUBMITTED)

    def cancel(self, order_id: str) -> OrderResult:
        self.cancelled.append(order_id)
        return OrderResult(client_order_id=order_id, status=OrderStatus.CANCELLED)

    def positions(self) -> list[Position]:
        return []


class RecordingAlertSink:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, str]] = []

    def send(self, severity: str, message: str) -> None:
        self.alerts.append((severity, message))
