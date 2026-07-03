"""Ledger accounting (spec 04): fills + marks -> cost-adjusted equity curve
and FIFO round trips. Slippage/commission are applied here, deterministically,
and declared in the report."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from algotrade.backtest.accounting import FillRecord, Ledger
from algotrade.domain.enums import OrderSide

T0 = datetime(2026, 1, 5, tzinfo=UTC)


def make_fill(day: int, side: OrderSide, qty: str, price: str) -> FillRecord:
    return FillRecord(
        timestamp=T0 + timedelta(days=day),
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
    )


class TestCosts:
    def test_buy_price_slips_up_and_sell_price_slips_down(self) -> None:
        ledger = Ledger(
            initial_cash=Decimal("10000"), slippage_bps=Decimal("100"), commission_bps=Decimal("0")
        )
        ledger.apply_fill(make_fill(1, OrderSide.BUY, "10", "100"))
        # 100 bps = 1%: buy executes at 101
        assert ledger.cash == Decimal("10000") - Decimal("1010")
        ledger.apply_fill(make_fill(2, OrderSide.SELL, "10", "100"))
        # sell executes at 99
        assert ledger.cash == Decimal("10000") - Decimal("1010") + Decimal("990")

    def test_commission_charged_on_notional_both_ways(self) -> None:
        ledger = Ledger(
            initial_cash=Decimal("10000"), slippage_bps=Decimal("0"), commission_bps=Decimal("10")
        )
        ledger.apply_fill(make_fill(1, OrderSide.BUY, "10", "100"))
        # 10 bps of 1000 notional = 1
        assert ledger.cash == Decimal("10000") - Decimal("1000") - Decimal("1")
        assert ledger.total_commission == Decimal("1")

    def test_zero_cost_roundtrip_preserves_cash(self) -> None:
        ledger = Ledger(
            initial_cash=Decimal("5000"), slippage_bps=Decimal("0"), commission_bps=Decimal("0")
        )
        ledger.apply_fill(make_fill(1, OrderSide.BUY, "10", "100"))
        ledger.apply_fill(make_fill(2, OrderSide.SELL, "10", "100"))
        assert ledger.cash == Decimal("5000")
        assert ledger.position == Decimal("0")


class TestMarks:
    def test_equity_marks_position_to_close(self) -> None:
        ledger = Ledger(
            initial_cash=Decimal("10000"), slippage_bps=Decimal("0"), commission_bps=Decimal("0")
        )
        ledger.apply_fill(make_fill(1, OrderSide.BUY, "10", "100"))
        point = ledger.mark(T0 + timedelta(days=2), close=Decimal("110"))
        assert point.equity == Decimal("10000") - Decimal("1000") + Decimal("1100")
        assert point.position == Decimal("10")

    def test_short_position_marks_negatively(self) -> None:
        ledger = Ledger(
            initial_cash=Decimal("10000"), slippage_bps=Decimal("0"), commission_bps=Decimal("0")
        )
        ledger.apply_fill(make_fill(1, OrderSide.SELL, "10", "100"))
        point = ledger.mark(T0 + timedelta(days=2), close=Decimal("120"))
        # short 10 @ 100, price rose to 120 -> equity down 200
        assert point.equity == Decimal("9800")
        assert point.position == Decimal("-10")


class TestRoundTrips:
    def test_profitable_long_roundtrip_is_a_win(self) -> None:
        ledger = Ledger(
            initial_cash=Decimal("10000"), slippage_bps=Decimal("0"), commission_bps=Decimal("0")
        )
        ledger.apply_fill(make_fill(1, OrderSide.BUY, "10", "100"))
        ledger.apply_fill(make_fill(3, OrderSide.SELL, "10", "105"))
        [trip] = ledger.round_trips
        assert trip.pnl == Decimal("50")
        assert trip.is_win

    def test_losing_short_roundtrip_counts_costs(self) -> None:
        ledger = Ledger(
            initial_cash=Decimal("10000"), slippage_bps=Decimal("0"), commission_bps=Decimal("10")
        )
        ledger.apply_fill(make_fill(1, OrderSide.SELL, "10", "100"))
        ledger.apply_fill(make_fill(2, OrderSide.BUY, "10", "103"))
        [trip] = ledger.round_trips
        # short pnl -30, commissions 1.00 + 1.03
        assert trip.pnl == Decimal("-30") - Decimal("1") - Decimal("1.03")
        assert not trip.is_win

    def test_open_position_is_not_a_round_trip(self) -> None:
        ledger = Ledger(
            initial_cash=Decimal("10000"), slippage_bps=Decimal("0"), commission_bps=Decimal("0")
        )
        ledger.apply_fill(make_fill(1, OrderSide.BUY, "10", "100"))
        assert ledger.round_trips == []

    def test_turnover_notional_accumulates_both_sides(self) -> None:
        ledger = Ledger(
            initial_cash=Decimal("10000"), slippage_bps=Decimal("0"), commission_bps=Decimal("0")
        )
        ledger.apply_fill(make_fill(1, OrderSide.BUY, "10", "100"))
        ledger.apply_fill(make_fill(2, OrderSide.SELL, "10", "110"))
        assert ledger.traded_notional == Decimal("1000") + Decimal("1100")
