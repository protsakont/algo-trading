"""Pre-trade risk checks (spec 05).

Every check returns a RiskVerdict — never an exception as control flow — and
treats missing data as grounds for rejection (default-deny). Exposure-REDUCING
orders are allowed through position/exposure limits and breaker lockouts:
being able to get OUT is itself a risk control.
"""

from decimal import Decimal

from algotrade.domain.dto import Order, Position, RiskVerdict
from algotrade.domain.enums import OrderSide
from algotrade.interfaces import AlertSink
from algotrade.risk.config import RiskConfig
from algotrade.risk.halt import FileHaltStore
from algotrade.risk.state import AccountSnapshot

_HUNDRED = Decimal(100)


def _signed_quantity(order: Order) -> Decimal:
    return order.quantity if order.side is OrderSide.BUY else -order.quantity


def _held_quantity(symbol: str, positions: list[Position]) -> Decimal:
    return sum((p.quantity for p in positions if p.symbol == symbol), Decimal(0))


def _reference_price(order: Order, snapshot: AccountSnapshot) -> Decimal | None:
    if order.limit_price is not None:
        return order.limit_price
    return snapshot.last_prices.get(order.symbol)


def _is_exposure_reducing(order: Order, positions: list[Position]) -> bool:
    """Strictly closing: the resulting position must lie between 0 and the
    held position (sign preserved or flat). A SELL bigger than the long is
    NOT reducing — it flips into a fresh short (a magnitude-only test let
    flips masquerade as close-only orders)."""
    held = _held_quantity(order.symbol, positions)
    if held == 0:
        return False
    resulting = held + _signed_quantity(order)
    same_sign_or_flat = resulting == 0 or (resulting > 0) == (held > 0)
    return same_sign_or_flat and abs(resulting) < abs(held)


def _approve(check_name: str, reason: str) -> RiskVerdict:
    return RiskVerdict(approved=True, reason=reason, check_name=check_name)


def _reject(check_name: str, reason: str) -> RiskVerdict:
    return RiskVerdict(approved=False, reason=reason, check_name=check_name)


class MaxPositionCheck:
    """Resulting position per symbol must stay within max_position_pct of
    equity; reducing an already-oversized position is always allowed."""

    name = "MaxPositionCheck"

    def __init__(self, config: RiskConfig) -> None:
        self._max_pct = config.max_position_pct

    def evaluate(
        self, order: Order, positions: list[Position], snapshot: AccountSnapshot
    ) -> RiskVerdict:
        price = _reference_price(order, snapshot)
        if price is None:
            return _reject(self.name, f"no reference price for {order.symbol} (default-deny)")
        if _is_exposure_reducing(order, positions):
            return _approve(self.name, "order reduces the position")

        resulting = _held_quantity(order.symbol, positions) + _signed_quantity(order)
        notional = abs(resulting) * price
        limit = snapshot.equity * self._max_pct / _HUNDRED
        if notional > limit:
            return _reject(
                self.name,
                f"resulting {order.symbol} position {notional} exceeds "
                f"{self._max_pct}% of equity ({limit})",
            )
        return _approve(self.name, f"position {notional} within limit {limit}")


class MaxGrossExposureCheck:
    """Total gross notional across all symbols must stay within limit;
    reducing gross exposure is always allowed."""

    name = "MaxGrossExposureCheck"

    def __init__(self, config: RiskConfig) -> None:
        self._max_pct = config.max_gross_exposure_pct

    def evaluate(
        self, order: Order, positions: list[Position], snapshot: AccountSnapshot
    ) -> RiskVerdict:
        order_price = _reference_price(order, snapshot)
        if order_price is None:
            return _reject(self.name, f"no reference price for {order.symbol} (default-deny)")

        # Aggregate by symbol FIRST — applying the order delta per position
        # row would understate the resulting gross with duplicate rows.
        net_by_symbol: dict[str, Decimal] = {}
        for held in positions:
            net_by_symbol[held.symbol] = net_by_symbol.get(held.symbol, Decimal(0)) + held.quantity

        prices: dict[str, Decimal] = {}
        for symbol in net_by_symbol:
            price = snapshot.last_prices.get(symbol)
            if price is None and symbol == order.symbol:
                price = order_price
            if price is None:
                return _reject(self.name, f"held position {symbol} has no price (default-deny)")
            prices[symbol] = price
        prices.setdefault(order.symbol, order_price)

        resulting_by_symbol = dict(net_by_symbol)
        resulting_by_symbol[order.symbol] = net_by_symbol.get(
            order.symbol, Decimal(0)
        ) + _signed_quantity(order)

        current_gross = sum(
            (abs(qty) * prices[sym] for sym, qty in net_by_symbol.items()), Decimal(0)
        )
        resulting_gross = sum(
            (abs(qty) * prices[sym] for sym, qty in resulting_by_symbol.items()), Decimal(0)
        )

        limit = snapshot.equity * self._max_pct / _HUNDRED
        if resulting_gross <= limit or resulting_gross < current_gross:
            return _approve(self.name, f"gross exposure {resulting_gross} within limit {limit}")
        return _reject(
            self.name,
            f"gross exposure {resulting_gross} exceeds {self._max_pct}% of equity ({limit})",
        )


class MaxOrderSizeCheck:
    """Fat-finger guard: one order's notional is capped at max_order_pct of
    equity, no exceptions — not even reducing orders (a fat-fingered close
    is still a fat finger)."""

    name = "MaxOrderSizeCheck"

    def __init__(self, config: RiskConfig) -> None:
        self._max_pct = config.max_order_pct

    def evaluate(
        self, order: Order, positions: list[Position], snapshot: AccountSnapshot
    ) -> RiskVerdict:
        price = _reference_price(order, snapshot)
        if price is None:
            return _reject(self.name, f"no reference price for {order.symbol} (default-deny)")
        notional = order.quantity * price
        limit = snapshot.equity * self._max_pct / _HUNDRED
        if notional > limit:
            return _reject(
                self.name,
                f"order notional {notional} exceeds {self._max_pct}% of equity ({limit})",
            )
        return _approve(self.name, f"order notional {notional} within limit {limit}")


class DailyLossCircuitBreaker:
    """At the daily loss limit, only exposure-reducing orders pass."""

    name = "DailyLossCircuitBreaker"

    def __init__(self, config: RiskConfig) -> None:
        self._limit_pct = config.daily_loss_limit_pct

    def evaluate(
        self, order: Order, positions: list[Position], snapshot: AccountSnapshot
    ) -> RiskVerdict:
        limit = snapshot.day_start_equity * self._limit_pct / _HUNDRED
        if snapshot.daily_pnl > -limit:
            return _approve(self.name, f"daily pnl {snapshot.daily_pnl} above -{limit}")
        if _is_exposure_reducing(order, positions):
            return _approve(self.name, "daily loss limit hit - exposure-reducing order allowed")
        return _reject(
            self.name,
            f"daily loss limit breached (pnl {snapshot.daily_pnl}, limit -{limit}) - "
            "only exposure-reducing orders are allowed",
        )


class DrawdownCircuitBreaker:
    """Equity below the high-water mark by more than max_drawdown_pct trips
    the persisted halt and fires a CRITICAL alert."""

    name = "DrawdownCircuitBreaker"

    def __init__(self, config: RiskConfig, halt: FileHaltStore, alerts: AlertSink) -> None:
        self._max_dd = config.max_drawdown_pct
        self._halt = halt
        self._alerts = alerts

    def evaluate(
        self, order: Order, positions: list[Position], snapshot: AccountSnapshot
    ) -> RiskVerdict:
        drawdown_pct = (1 - snapshot.equity / snapshot.high_water_mark) * _HUNDRED
        if drawdown_pct < self._max_dd:
            return _approve(self.name, f"drawdown {drawdown_pct:.2f}% within {self._max_dd}%")

        reason = (
            f"drawdown {drawdown_pct:.2f}% breached limit {self._max_dd}% "
            f"(equity {snapshot.equity}, HWM {snapshot.high_water_mark})"
        )
        if not self._halt.is_halted():
            # Alert only on the transition into breach - halt() keeps the
            # first reason, alerts must not re-fire on every close attempt.
            self._halt.halt(reason)
            self._alerts.send("CRITICAL", reason)
        if _is_exposure_reducing(order, positions):
            # De-risking must stay possible during a drawdown breach -
            # blocking the exit would turn a halt into a trap.
            return _approve(self.name, f"{reason} - exposure-reducing order allowed")
        return _reject(self.name, reason)


class HaltStateCheck:
    """While halted, everything is rejected except close-only (exposure-
    reducing) orders. Runs FIRST in the chain."""

    name = "HaltStateCheck"

    def __init__(self, halt: FileHaltStore) -> None:
        self._halt = halt

    def evaluate(
        self, order: Order, positions: list[Position], snapshot: AccountSnapshot
    ) -> RiskVerdict:
        if not self._halt.is_halted():
            return _approve(self.name, "not halted")
        if _is_exposure_reducing(order, positions):
            return _approve(self.name, "halted - close-only order allowed")
        return _reject(
            self.name,
            f"trading halted ({self._halt.reason()}) - only close-only orders are allowed; "
            "manual reset required",
        )
