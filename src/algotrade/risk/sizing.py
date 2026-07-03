"""Position sizers (spec 05): volatility targeting is the default; fixed
fraction is the alternative. Both size to ZERO on any missing input —
default-deny never guesses a position size.

Quantities round DOWN to whole units and scale with |signal.strength|.
Direction is the execution layer's concern; sizers return magnitude only.
"""

from collections.abc import Callable
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

from algotrade.domain.dto import Position, Signal

PriceLookup = Callable[[str], Decimal | None]
VolatilityLookup = Callable[[str], Decimal | None]

_HUNDRED = Decimal(100)
_WHOLE = Decimal(1)


def _to_quantity(notional: Decimal, price: Decimal) -> Decimal:
    try:
        return (notional / price).quantize(_WHOLE, rounding=ROUND_DOWN)
    except InvalidOperation:
        # Quotient too large to quantize (pathological equity/price) - a
        # sizer that cannot compute a sane size sizes zero, never guesses.
        return Decimal(0)


class FixedFractionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fraction_pct: Decimal = Field(default=Decimal(1), gt=0, le=100)


class FixedFractionSizer:
    def __init__(self, config: FixedFractionConfig, price_lookup: PriceLookup) -> None:
        self._config = config
        self._price = price_lookup

    def size(self, signal: Signal, equity: Decimal, positions: list[Position]) -> Decimal:
        price = self._price(signal.symbol)
        if price is None or price <= 0:
            return Decimal(0)
        strength = Decimal(str(abs(signal.strength)))
        notional = equity * self._config.fraction_pct / _HUNDRED * strength
        return _to_quantity(notional, price)


class VolatilityTargetConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Contribution target: position_notional * asset_daily_vol ~ equity * target.
    target_daily_vol_pct: Decimal = Field(default=Decimal(1), gt=0, le=100)
    # Hard cap regardless of how quiet the asset looks (quiet != safe).
    max_position_pct: Decimal = Field(default=Decimal(10), gt=0, le=100)


class VolatilityTargetSizer:
    """notional = equity * target_vol / asset_vol, capped at max_position_pct.

    The volatility lookup should return the asset's daily return volatility
    as a fraction (e.g. 0.02 for 2%) — the feature pipeline's vol_{n} feature
    is the intended source."""

    def __init__(
        self,
        config: VolatilityTargetConfig,
        price_lookup: PriceLookup,
        volatility_lookup: VolatilityLookup,
    ) -> None:
        self._config = config
        self._price = price_lookup
        self._volatility = volatility_lookup

    def size(self, signal: Signal, equity: Decimal, positions: list[Position]) -> Decimal:
        price = self._price(signal.symbol)
        volatility = self._volatility(signal.symbol)
        if price is None or price <= 0 or volatility is None or volatility <= 0:
            return Decimal(0)

        strength = Decimal(str(abs(signal.strength)))
        risk_budget = equity * self._config.target_daily_vol_pct / _HUNDRED * strength
        notional = risk_budget / volatility
        cap = equity * self._config.max_position_pct / _HUNDRED
        return _to_quantity(min(notional, cap), price)
