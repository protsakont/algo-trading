"""Pre-trade checks (spec 05): boundary tests per check plus hypothesis
property tests proving NO input gets an over-limit order approved."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from algotrade.domain.dto import Order, Position
from algotrade.domain.enums import OrderSide, OrderType
from algotrade.risk.checks import (
    DailyLossCircuitBreaker,
    DrawdownCircuitBreaker,
    HaltStateCheck,
    MaxGrossExposureCheck,
    MaxOrderSizeCheck,
    MaxPositionCheck,
)
from algotrade.risk.config import RiskConfig
from algotrade.risk.halt import FileHaltStore
from algotrade.risk.state import AccountSnapshot
from tests.fakes import RecordingAlertSink

TS = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
CONFIG = RiskConfig()  # conservative defaults


def make_order(qty: str = "10", side: OrderSide = OrderSide.BUY, symbol: str = "AAPL") -> Order:
    return Order(
        client_order_id="t-1",
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        created_at=TS,
    )


def make_snapshot(
    equity: str = "100000",
    daily_pnl: str = "0",
    hwm: str = "100000",
    prices: dict[str, str] | None = None,
) -> AccountSnapshot:
    prices = prices if prices is not None else {"AAPL": "100"}
    return AccountSnapshot(
        timestamp=TS,
        equity=Decimal(equity),
        day_start_equity=Decimal("100000"),
        daily_pnl=Decimal(daily_pnl),
        high_water_mark=Decimal(hwm),
        last_prices={k: Decimal(v) for k, v in prices.items()},
    )


def position(symbol: str, qty: str, price: str = "100") -> Position:
    return Position(symbol=symbol, quantity=Decimal(qty), avg_entry_price=Decimal(price))


class TestMaxPositionCheck:
    check = MaxPositionCheck(CONFIG)  # 10% of 100k equity = 10k notional

    def test_within_limit_approves(self) -> None:
        verdict = self.check.evaluate(make_order("99"), [], make_snapshot())
        assert verdict.approved

    def test_over_limit_rejects_with_reason(self) -> None:
        verdict = self.check.evaluate(make_order("101"), [], make_snapshot())
        assert not verdict.approved
        assert verdict.check_name == "MaxPositionCheck"
        assert "10" in verdict.reason  # limit is visible in the reason

    def test_existing_position_counts_toward_limit(self) -> None:
        verdict = self.check.evaluate(make_order("60"), [position("AAPL", "50")], make_snapshot())
        assert not verdict.approved  # 50 + 60 = 110 > 100 max shares

    def test_reducing_an_oversized_position_is_allowed(self) -> None:
        verdict = self.check.evaluate(
            make_order("50", side=OrderSide.SELL), [position("AAPL", "150")], make_snapshot()
        )
        assert verdict.approved

    def test_missing_reference_price_rejects(self) -> None:
        verdict = self.check.evaluate(make_order(), [], make_snapshot(prices={}))
        assert not verdict.approved
        assert "price" in verdict.reason

    @given(
        qty=st.decimals(min_value="1", max_value="1000000", places=0),
        price=st.decimals(min_value="0.01", max_value="100000", places=2),
        equity=st.decimals(min_value="1", max_value="10000000", places=2),
        held=st.decimals(min_value="-100000", max_value="100000", places=0),
        side=st.sampled_from([OrderSide.BUY, OrderSide.SELL]),
    )
    def test_property_no_approved_order_exceeds_limit(
        self, qty: Decimal, price: Decimal, equity: Decimal, held: Decimal, side: OrderSide
    ) -> None:
        """Spec 05 acceptance: no input gets an over-limit order approved,
        unless it strictly closes. The oracle here is deliberately INDEPENDENT
        of the implementation: closing means opposite side of the net position
        with quantity not exceeding it (no flip)."""
        snapshot = AccountSnapshot(
            timestamp=TS,
            equity=equity,
            day_start_equity=equity,
            daily_pnl=Decimal(0),
            high_water_mark=equity,
            last_prices={"AAPL": price},
        )
        positions = [position("AAPL", str(held), "1")] if held else []
        verdict = self.check.evaluate(make_order(str(qty), side=side), positions, snapshot)

        signed = qty if side is OrderSide.BUY else -qty
        resulting_notional = abs(held + signed) * price
        limit = equity * CONFIG.max_position_pct / 100
        is_strict_close = (held > 0 and side is OrderSide.SELL and qty <= held) or (
            held < 0 and side is OrderSide.BUY and qty <= -held
        )
        if verdict.approved:
            assert resulting_notional <= limit or is_strict_close, (
                f"approved over-limit non-closing order: held={held} side={side} qty={qty}"
            )


class TestMaxGrossExposureCheck:
    check = MaxGrossExposureCheck(CONFIG)  # 50% of equity

    def test_within_limit_approves(self) -> None:
        verdict = self.check.evaluate(
            make_order("100"),
            [position("MSFT", "200")],
            make_snapshot(prices={"AAPL": "100", "MSFT": "100"}),
        )
        assert verdict.approved  # 20k + 10k = 30k <= 50k

    def test_over_limit_rejects(self) -> None:
        verdict = self.check.evaluate(
            make_order("200"),
            [position("MSFT", "350")],
            make_snapshot(prices={"AAPL": "100", "MSFT": "100"}),
        )
        assert not verdict.approved  # 35k + 20k = 55k > 50k

    def test_exposure_reducing_order_is_allowed_even_over_limit(self) -> None:
        verdict = self.check.evaluate(
            make_order("100", side=OrderSide.SELL),
            [position("AAPL", "600")],
            make_snapshot(prices={"AAPL": "100"}),
        )
        assert verdict.approved  # 60k -> 50k, reducing

    def test_unpriceable_held_position_rejects(self) -> None:
        """Ambiguous state = reject: we hold MSFT but cannot price it."""
        verdict = self.check.evaluate(
            make_order("1"), [position("MSFT", "10")], make_snapshot(prices={"AAPL": "100"})
        )
        assert not verdict.approved
        assert "MSFT" in verdict.reason

    def test_held_order_symbol_falls_back_to_limit_price(self) -> None:
        """We hold AAPL, no market price, but the LIMIT order carries one."""
        limit_order = Order(
            client_order_id="t-3",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            limit_price=Decimal("100"),
            created_at=TS,
        )
        verdict = self.check.evaluate(
            limit_order, [position("AAPL", "10")], make_snapshot(prices={})
        )
        assert verdict.approved  # resulting 20 * 100 = 2000 <= 50000

    def test_unpriceable_order_symbol_rejects(self) -> None:
        verdict = self.check.evaluate(make_order("1"), [], make_snapshot(prices={}))
        assert not verdict.approved
        assert "default-deny" in verdict.reason


class TestMaxOrderSizeCheck:
    check = MaxOrderSizeCheck(CONFIG)  # 5% of 100k = 5k notional

    def test_normal_order_approves(self) -> None:
        assert self.check.evaluate(make_order("49"), [], make_snapshot()).approved

    def test_limit_order_uses_its_own_price_as_reference(self) -> None:
        limit_order = Order(
            client_order_id="t-2",
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            limit_price=Decimal("60"),
            created_at=TS,
        )
        # No market price available, but 100 * 60 = 6000 > 5000 limit
        verdict = self.check.evaluate(limit_order, [], make_snapshot(prices={}))
        assert not verdict.approved

    def test_missing_price_rejects(self) -> None:
        verdict = self.check.evaluate(make_order(), [], make_snapshot(prices={}))
        assert not verdict.approved
        assert "default-deny" in verdict.reason

    def test_fat_finger_rejects(self) -> None:
        verdict = self.check.evaluate(make_order("51"), [], make_snapshot())
        assert not verdict.approved
        assert verdict.check_name == "MaxOrderSizeCheck"

    @given(
        qty=st.decimals(min_value="1", max_value="1000000", places=0),
        price=st.decimals(min_value="0.01", max_value="100000", places=2),
        equity=st.decimals(min_value="1", max_value="10000000", places=2),
    )
    def test_property_no_oversized_order_approved(
        self, qty: Decimal, price: Decimal, equity: Decimal
    ) -> None:
        snapshot = AccountSnapshot(
            timestamp=TS,
            equity=equity,
            day_start_equity=equity,
            daily_pnl=Decimal(0),
            high_water_mark=equity,
            last_prices={"AAPL": price},
        )
        verdict = self.check.evaluate(make_order(str(qty)), [], snapshot)
        if verdict.approved:
            assert qty * price <= equity * CONFIG.max_order_pct / 100


class TestDailyLossCircuitBreaker:
    check = DailyLossCircuitBreaker(CONFIG)  # 3% of day-start equity = 3000

    def test_normal_day_approves(self) -> None:
        verdict = self.check.evaluate(make_order(), [], make_snapshot(daily_pnl="-2999"))
        assert verdict.approved

    def test_breach_rejects_new_exposure(self) -> None:
        verdict = self.check.evaluate(make_order(), [], make_snapshot(daily_pnl="-3000"))
        assert not verdict.approved
        assert "daily loss" in verdict.reason.lower()

    def test_breach_still_allows_exposure_reducing_orders(self) -> None:
        verdict = self.check.evaluate(
            make_order("10", side=OrderSide.SELL),
            [position("AAPL", "50")],
            make_snapshot(daily_pnl="-5000"),
        )
        assert verdict.approved


class TestDrawdownCircuitBreaker:
    def test_below_threshold_approves(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        halt = FileHaltStore(tmp_path / "halt.json")
        alerts = RecordingAlertSink()
        check = DrawdownCircuitBreaker(CONFIG, halt, alerts)
        verdict = check.evaluate(make_order(), [], make_snapshot(equity="81000", hwm="100000"))
        assert verdict.approved
        assert not halt.is_halted()

    def test_breach_halts_alerts_critical_and_rejects(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Spec 05: below HWM by Y% -> halt + CRITICAL alert."""
        halt = FileHaltStore(tmp_path / "halt.json")
        alerts = RecordingAlertSink()
        check = DrawdownCircuitBreaker(CONFIG, halt, alerts)

        verdict = check.evaluate(make_order(), [], make_snapshot(equity="80000", hwm="100000"))

        assert not verdict.approved
        assert halt.is_halted()
        assert tuple({severity for severity, _ in alerts.alerts}) == ("CRITICAL",)
        assert "drawdown" in (halt.reason() or "").lower()


class TestHaltStateCheck:
    def test_not_halted_approves(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        check = HaltStateCheck(FileHaltStore(tmp_path / "halt.json"))
        assert check.evaluate(make_order(), [], make_snapshot()).approved

    def test_halted_rejects_new_exposure(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        halt = FileHaltStore(tmp_path / "halt.json")
        halt.halt("test")
        check = HaltStateCheck(halt)
        verdict = check.evaluate(make_order(), [], make_snapshot())
        assert not verdict.approved
        assert "halt" in verdict.reason.lower()

    def test_halted_allows_close_only(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        halt = FileHaltStore(tmp_path / "halt.json")
        halt.halt("test")
        check = HaltStateCheck(halt)
        verdict = check.evaluate(
            make_order("10", side=OrderSide.SELL), [position("AAPL", "50")], make_snapshot()
        )
        assert verdict.approved

    @given(qty=st.decimals(min_value="1", max_value="10000", places=0))
    def test_property_halted_never_approves_exposure_increase(
        self, tmp_path_factory: pytest.TempPathFactory, qty: Decimal
    ) -> None:
        halt = FileHaltStore(tmp_path_factory.mktemp("halt") / "halt.json")
        halt.halt("breach")
        check = HaltStateCheck(halt)
        verdict = check.evaluate(make_order(str(qty)), [], make_snapshot())
        assert not verdict.approved


class TestPositionFlipRegression:
    """qa MUST-1: a SELL bigger than the long flips into a short - that is
    OPENING exposure and must never pass as 'close-only'."""

    def test_halted_rejects_position_flip(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        halt = FileHaltStore(tmp_path / "halt.json")
        halt.halt("breach")
        check = HaltStateCheck(halt)
        verdict = check.evaluate(
            make_order("100", side=OrderSide.SELL), [position("AAPL", "50")], make_snapshot()
        )
        assert not verdict.approved

    def test_daily_loss_lockout_rejects_position_flip(self) -> None:
        check = DailyLossCircuitBreaker(CONFIG)
        verdict = check.evaluate(
            make_order("99", side=OrderSide.SELL),
            [position("AAPL", "50")],
            make_snapshot(daily_pnl="-99000"),
        )
        assert not verdict.approved

    def test_max_position_rejects_flip_beyond_limit(self) -> None:
        check = MaxPositionCheck(CONFIG)
        verdict = check.evaluate(
            make_order("250", side=OrderSide.SELL), [position("AAPL", "50")], make_snapshot()
        )
        assert not verdict.approved  # resulting short 200 = 20k > 10k limit

    def test_full_close_is_still_allowed(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        halt = FileHaltStore(tmp_path / "halt.json")
        halt.halt("breach")
        check = HaltStateCheck(halt)
        verdict = check.evaluate(
            make_order("50", side=OrderSide.SELL), [position("AAPL", "50")], make_snapshot()
        )
        assert verdict.approved


class TestGrossExposureAggregation:
    """qa MUST-2: duplicate position rows for one symbol must be netted before
    applying the order delta, or resulting gross is understated."""

    def test_duplicate_rows_do_not_understate_gross(self) -> None:
        check = MaxGrossExposureCheck(CONFIG)  # 50% of 100k = 50k
        verdict = check.evaluate(
            make_order("100", side=OrderSide.SELL),
            [position("AAPL", "100"), position("AAPL", "100"), position("MSFT", "450")],
            make_snapshot(prices={"AAPL": "100", "MSFT": "100"}),
        )
        # True resulting gross = |200-100|*100 + 45000 = 55000. The order IS
        # gross-reducing (65k -> 55k) so approval is legitimate - but the
        # verdict must be reasoned from the TRUE number, not a per-row 45000.
        assert verdict.approved
        assert "55000" in verdict.reason

    def test_duplicate_rows_increasing_beyond_limit_rejects(self) -> None:
        check = MaxGrossExposureCheck(CONFIG)
        verdict = check.evaluate(
            make_order("100", side=OrderSide.BUY),
            [position("AAPL", "100"), position("AAPL", "100"), position("MSFT", "450")],
            make_snapshot(prices={"AAPL": "100", "MSFT": "100"}),
        )
        # net 200 -> 300: resulting 30000 + 45000 = 75000 > 50000, increasing
        assert not verdict.approved
        assert "75000" in verdict.reason

    def test_offsetting_rows_net_to_flat_before_the_delta(self) -> None:
        check = MaxGrossExposureCheck(CONFIG)
        verdict = check.evaluate(
            make_order("550", side=OrderSide.BUY),
            [position("AAPL", "250"), position("AAPL", "-250")],
            make_snapshot(prices={"AAPL": "100"}),
        )
        # true current gross is 0 (rows offset); resulting 55000 > 50000
        assert not verdict.approved

    @given(
        rows=st.lists(
            st.tuples(
                st.sampled_from(["AAPL", "MSFT"]),
                st.decimals(min_value="-500", max_value="500", places=0),
            ),
            max_size=4,
        ),
        qty=st.decimals(min_value="1", max_value="1000", places=0),
        side=st.sampled_from([OrderSide.BUY, OrderSide.SELL]),
    )
    def test_property_no_over_limit_gross_approved(
        self, rows: list[tuple[str, Decimal]], qty: Decimal, side: OrderSide
    ) -> None:
        prices = {"AAPL": Decimal("100"), "MSFT": Decimal("50")}
        check = MaxGrossExposureCheck(CONFIG)
        positions = [position(sym, str(q)) for sym, q in rows if q]
        snapshot = make_snapshot(prices={"AAPL": "100", "MSFT": "50"})

        verdict = check.evaluate(make_order(str(qty), side=side), positions, snapshot)

        # Independent oracle: net per symbol, apply delta once, price it.
        net: dict[str, Decimal] = {}
        for sym, q in rows:
            if q:
                net[sym] = net.get(sym, Decimal(0)) + q
        current = sum((abs(q) * prices[s] for s, q in net.items()), Decimal(0))
        signed = qty if side is OrderSide.BUY else -qty
        net["AAPL"] = net.get("AAPL", Decimal(0)) + signed
        resulting = sum((abs(q) * prices[s] for s, q in net.items()), Decimal(0))
        limit = Decimal("100000") * CONFIG.max_gross_exposure_pct / 100
        if verdict.approved:
            assert resulting <= limit or resulting < current
