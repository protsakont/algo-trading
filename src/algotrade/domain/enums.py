"""Domain enums shared across modules (specs 03, 06, 08)."""

from enum import StrEnum, unique


@unique
class SignalDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@unique
class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@unique
class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


@unique
class OrderStatus(StrEnum):
    """Order lifecycle states (spec 06). Transitions are enforced by the
    execution state machine, not here."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@unique
class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"
