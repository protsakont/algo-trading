"""Frozen domain DTOs (spec 01).

Rules enforced here:
- immutable across layers (``frozen=True``)
- money/quantities are ``Decimal``, never ``float``
- timestamps are timezone-aware and normalized to UTC
- engine/vendor objects (nautilus, vectorbt) map to these only inside adapters
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .enums import OrderSide, OrderStatus, OrderType, SignalDirection


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError(
            "money/quantity values must never be float (CLAUDE.md rule 8) — "
            "pass Decimal, int, or str"
        )
    return value


# Prices, quantities, and P&L: Decimal semantics, float inputs rejected outright.
Money = Annotated[Decimal, BeforeValidator(_reject_float)]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=False)

    @field_validator("*", mode="after")
    @classmethod
    def _require_utc(cls, value: object) -> object:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("timestamps must be timezone-aware")
            return value.astimezone(UTC)
        return value


class Bar(FrozenModel):
    """One OHLCV bar. Invalid market data must be rejected before this point;
    the sanity checks here are a last line of defense (spec 02)."""

    symbol: str = Field(min_length=1)
    timestamp: datetime
    timeframe: str = Field(min_length=1, examples=["1m", "1h", "1d"])
    open: Money = Field(gt=0)
    high: Money = Field(gt=0)
    low: Money = Field(gt=0)
    close: Money = Field(gt=0)
    volume: Money = Field(ge=0)

    @model_validator(mode="after")
    def _ohlc_sanity(self) -> Self:
        if self.high < self.low:
            raise ValueError(f"high {self.high} is below low {self.low}")
        for name in ("open", "close"):
            price: Decimal = getattr(self, name)
            if not (self.low <= price <= self.high):
                raise ValueError(f"{name} {price} outside [low, high] range")
        return self


class FeatureSet(FrozenModel):
    """Named feature values computed from bars as of ``timestamp``.

    Features at time t may only use data <= t (no lookahead, spec 02).
    Feature values are analytics, not money, so ``float`` is acceptable.
    """

    symbol: str = Field(min_length=1)
    timestamp: datetime
    features: dict[str, float]


class Signal(FrozenModel):
    """Strategy output (spec 03): direction plus conviction in [-1, 1]."""

    strategy_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    direction: SignalDirection
    strength: float = Field(ge=-1.0, le=1.0)
    timestamp: datetime
    metadata: dict[str, str] = Field(default_factory=dict)


class Order(FrozenModel):
    """Order intent. ``client_order_id`` must be deterministic per signal for
    idempotent submission (spec 06)."""

    client_order_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    side: OrderSide
    order_type: OrderType
    quantity: Money = Field(gt=0)
    limit_price: Money | None = Field(default=None, gt=0)
    status: OrderStatus = OrderStatus.DRAFT
    created_at: datetime

    @model_validator(mode="after")
    def _limit_price_matches_type(self) -> Self:
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price must be omitted for market orders")
        return self


class OrderResult(FrozenModel):
    client_order_id: str = Field(min_length=1)
    status: OrderStatus
    filled_quantity: Money = Field(default=Decimal(0), ge=0)
    avg_fill_price: Money | None = Field(default=None, gt=0)
    message: str = ""


class Position(FrozenModel):
    """Signed position: negative quantity means short."""

    symbol: str = Field(min_length=1)
    quantity: Money
    avg_entry_price: Money = Field(gt=0)


class RiskVerdict(FrozenModel):
    """Risk decision (spec 05): always a verdict with a reason, never an
    exception used as control flow."""

    approved: bool
    reason: str
    check_name: str = Field(min_length=1)

    @model_validator(mode="after")
    def _every_verdict_needs_reason(self) -> Self:
        if not self.reason.strip():
            raise ValueError("every verdict must state a reason (spec 05)")
        return self
