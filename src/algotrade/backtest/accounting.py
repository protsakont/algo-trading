"""Deterministic backtest accounting (spec 04).

The engine produces raw fills; THIS layer applies the configured cost model —
slippage worsens the execution price, commission is charged on executed
notional — so cost assumptions are explicit, market-agnostic, and declared in
the report. FIFO lot matching turns fills into round trips for trade stats.
"""

from collections import deque
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from algotrade.domain.enums import OrderSide

_BPS = Decimal(10_000)


class FillRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    side: OrderSide
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)


class EquityPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    equity: Decimal
    position: Decimal


class RoundTrip(BaseModel):
    model_config = ConfigDict(frozen=True)

    opened_at: datetime
    closed_at: datetime
    quantity: Decimal = Field(gt=0)
    pnl: Decimal

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


class _Lot(BaseModel):
    """An open position lot awaiting its closing fill(s)."""

    model_config = ConfigDict(frozen=False)

    opened_at: datetime
    signed_quantity: Decimal  # >0 long, <0 short
    exec_price: Decimal
    commission: Decimal  # entry commission still unallocated


class Ledger:
    """Mutable within a single backtest run; never crosses a module boundary."""

    def __init__(
        self,
        initial_cash: Decimal,
        slippage_bps: Decimal,
        commission_bps: Decimal,
    ) -> None:
        self._cash = initial_cash
        self._slippage = slippage_bps / _BPS
        self._commission_rate = commission_bps / _BPS
        self._position = Decimal(0)
        self._total_commission = Decimal(0)
        self._traded_notional = Decimal(0)
        self._lots: deque[_Lot] = deque()
        self._round_trips: list[RoundTrip] = []

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def position(self) -> Decimal:
        return self._position

    @property
    def total_commission(self) -> Decimal:
        return self._total_commission

    @property
    def traded_notional(self) -> Decimal:
        return self._traded_notional

    @property
    def round_trips(self) -> list[RoundTrip]:
        return list(self._round_trips)

    def apply_fill(self, fill: FillRecord) -> None:
        is_buy = fill.side is OrderSide.BUY
        slip = self._slippage if is_buy else -self._slippage
        exec_price = fill.price * (1 + slip)
        notional = fill.quantity * exec_price
        commission = notional * self._commission_rate

        self._cash += -notional - commission if is_buy else notional - commission
        self._total_commission += commission
        self._traded_notional += notional

        signed = fill.quantity if is_buy else -fill.quantity
        self._match_lots(fill.timestamp, signed, exec_price, commission)
        self._position += signed

    def mark(self, timestamp: datetime, close: Decimal) -> EquityPoint:
        return EquityPoint(
            timestamp=timestamp,
            equity=self._cash + self._position * close,
            position=self._position,
        )

    def _match_lots(
        self, timestamp: datetime, signed: Decimal, exec_price: Decimal, commission: Decimal
    ) -> None:
        remaining = signed
        fill_qty = abs(signed)
        while remaining and self._lots and (self._lots[0].signed_quantity * remaining) < 0:
            lot = self._lots[0]
            matched = min(abs(remaining), abs(lot.signed_quantity))
            lot_direction = Decimal(1) if lot.signed_quantity > 0 else Decimal(-1)
            gross = (exec_price - lot.exec_price) * matched * lot_direction

            lot_commission_share = lot.commission * matched / abs(lot.signed_quantity)
            exit_commission_share = commission * matched / fill_qty
            pnl = gross - lot_commission_share - exit_commission_share
            self._round_trips.append(
                RoundTrip(
                    opened_at=lot.opened_at,
                    closed_at=timestamp,
                    quantity=matched,
                    # Commission shares divide non-terminating fractions;
                    # quantize so totals reconcile exactly.
                    pnl=pnl.quantize(Decimal("1.000000000000")),
                )
            )

            lot.commission -= lot_commission_share
            lot.signed_quantity += matched * -lot_direction
            remaining += matched * lot_direction
            if not lot.signed_quantity:
                self._lots.popleft()

        if remaining:
            self._lots.append(
                _Lot(
                    opened_at=timestamp,
                    signed_quantity=remaining,
                    exec_price=exec_price,
                    commission=commission * abs(remaining) / fill_qty,
                )
            )
