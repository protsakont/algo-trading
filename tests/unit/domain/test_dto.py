"""Domain DTO invariants (spec 01): frozen, Decimal money, tz-aware UTC time."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from algotrade.domain.dto import (
    Bar,
    FeatureSet,
    Order,
    OrderResult,
    Position,
    RiskVerdict,
    Signal,
)
from algotrade.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    SignalDirection,
)

TS = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


def make_bar(**overrides: object) -> Bar:
    fields: dict[str, object] = {
        "symbol": "AAPL",
        "timestamp": TS,
        "timeframe": "1d",
        "open": Decimal("100.0"),
        "high": Decimal("105.0"),
        "low": Decimal("99.0"),
        "close": Decimal("104.0"),
        "volume": Decimal("10000"),
    }
    fields.update(overrides)
    return Bar(**fields)  # type: ignore[arg-type]


def make_order(**overrides: object) -> Order:
    fields: dict[str, object] = {
        "client_order_id": "sig-abc-001",
        "symbol": "AAPL",
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("10"),
        "created_at": TS,
    }
    fields.update(overrides)
    return Order(**fields)  # type: ignore[arg-type]


class TestImmutability:
    def test_bar_is_frozen(self) -> None:
        bar = make_bar()
        with pytest.raises(ValidationError):
            bar.close = Decimal("999")  # type: ignore[misc]

    def test_order_is_frozen(self) -> None:
        order = make_order()
        with pytest.raises(ValidationError):
            order.quantity = Decimal("999999")  # type: ignore[misc]


class TestBar:
    def test_valid_bar_roundtrips(self) -> None:
        bar = make_bar()
        assert bar.close == Decimal("104.0")
        assert isinstance(bar.close, Decimal), "money must be Decimal, never float"

    def test_rejects_naive_timestamp(self) -> None:
        with pytest.raises(ValidationError, match=r"timezone-aware"):
            make_bar(timestamp=datetime(2026, 1, 5, 14, 30))

    def test_normalizes_timestamp_to_utc(self) -> None:
        bangkok = timezone(timedelta(hours=7))
        bar = make_bar(timestamp=datetime(2026, 1, 5, 21, 30, tzinfo=bangkok))
        assert bar.timestamp.utcoffset() == timedelta(0)
        assert bar.timestamp == TS

    def test_rejects_high_below_low(self) -> None:
        with pytest.raises(ValidationError, match="high"):
            make_bar(high=Decimal("98.0"))  # below low=99

    def test_rejects_close_outside_high_low_range(self) -> None:
        with pytest.raises(ValidationError):
            make_bar(close=Decimal("200.0"))  # above high=105

    def test_rejects_negative_volume(self) -> None:
        with pytest.raises(ValidationError):
            make_bar(volume=Decimal("-1"))


class TestSignal:
    def test_valid_signal(self) -> None:
        signal = Signal(
            strategy_id="sma_cross",
            symbol="AAPL",
            direction=SignalDirection.LONG,
            strength=0.75,
            timestamp=TS,
        )
        assert signal.metadata == {}

    @pytest.mark.parametrize("strength", [-1.01, 1.01, 5.0])
    def test_rejects_strength_outside_unit_interval(self, strength: float) -> None:
        with pytest.raises(ValidationError):
            Signal(
                strategy_id="sma_cross",
                symbol="AAPL",
                direction=SignalDirection.SHORT,
                strength=strength,
                timestamp=TS,
            )

    @pytest.mark.parametrize("strength", [-1.0, 0.0, 1.0])
    def test_accepts_strength_bounds_inclusive(self, strength: float) -> None:
        signal = Signal(
            strategy_id="sma_cross",
            symbol="AAPL",
            direction=SignalDirection.FLAT,
            strength=strength,
            timestamp=TS,
        )
        assert signal.strength == strength


class TestOrder:
    def test_new_order_defaults_to_draft(self) -> None:
        assert make_order().status is OrderStatus.DRAFT

    def test_rejects_non_positive_quantity(self) -> None:
        with pytest.raises(ValidationError):
            make_order(quantity=Decimal("0"))

    def test_limit_order_requires_limit_price(self) -> None:
        with pytest.raises(ValidationError, match="limit_price"):
            make_order(order_type=OrderType.LIMIT)

    def test_market_order_rejects_limit_price(self) -> None:
        with pytest.raises(ValidationError, match="limit_price"):
            make_order(limit_price=Decimal("100.5"))

    def test_limit_order_with_price_is_valid(self) -> None:
        order = make_order(order_type=OrderType.LIMIT, limit_price=Decimal("100.5"))
        assert order.limit_price == Decimal("100.5")


class TestOrderResult:
    def test_defaults(self) -> None:
        result = OrderResult(client_order_id="sig-abc-001", status=OrderStatus.SUBMITTED)
        assert result.filled_quantity == Decimal("0")
        assert result.avg_fill_price is None

    def test_rejects_negative_fill(self) -> None:
        with pytest.raises(ValidationError):
            OrderResult(
                client_order_id="sig-abc-001",
                status=OrderStatus.PARTIALLY_FILLED,
                filled_quantity=Decimal("-1"),
            )


class TestMoneyIsNeverFloat:
    def test_bar_rejects_float_price(self) -> None:
        with pytest.raises(ValidationError, match="never be float"):
            make_bar(open=100.1)

    def test_order_rejects_float_quantity(self) -> None:
        with pytest.raises(ValidationError, match="never be float"):
            make_order(quantity=10.5)

    def test_position_rejects_float_quantity(self) -> None:
        with pytest.raises(ValidationError, match="never be float"):
            Position(
                symbol="AAPL",
                quantity=-50.0,  # type: ignore[arg-type]
                avg_entry_price=Decimal("101.2"),
            )

    def test_string_and_int_inputs_still_coerce_to_decimal(self) -> None:
        bar = make_bar(open="100.25", volume=10000)
        assert bar.open == Decimal("100.25")
        assert isinstance(bar.volume, Decimal)


class TestRiskVerdict:
    def test_verdict_always_carries_reason_and_check_name(self) -> None:
        verdict = RiskVerdict(
            approved=False, reason="exceeds max position", check_name="MaxPositionCheck"
        )
        assert not verdict.approved
        assert verdict.reason
        assert verdict.check_name

    @pytest.mark.parametrize("approved", [True, False])
    def test_every_verdict_requires_nonempty_reason(self, approved: bool) -> None:
        with pytest.raises(ValidationError, match="reason"):
            RiskVerdict(approved=approved, reason="  ", check_name="MaxPositionCheck")


class TestPositionAndFeatures:
    def test_position_supports_short_via_negative_quantity(self) -> None:
        position = Position(
            symbol="AAPL", quantity=Decimal("-50"), avg_entry_price=Decimal("101.2")
        )
        assert position.quantity < 0

    def test_feature_set_holds_named_features(self) -> None:
        features = FeatureSet(
            symbol="AAPL", timestamp=TS, features={"sma_20": 101.5, "rsi_14": 55.0}
        )
        assert features.features["sma_20"] == pytest.approx(101.5)
