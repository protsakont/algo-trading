"""Risk limits (spec 05): every limit comes from config with conservative
defaults, and the chain logs the active values at startup."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RiskConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Pre-trade limits, all as percent of equity.
    max_position_pct: Decimal = Field(default=Decimal(10), gt=0, le=100)
    # le=300: leveraged gross beyond 3x equity is a config typo, not a plan.
    max_gross_exposure_pct: Decimal = Field(default=Decimal(50), gt=0, le=300)
    max_order_pct: Decimal = Field(default=Decimal(5), gt=0, le=100)

    # Circuit breakers.
    daily_loss_limit_pct: Decimal = Field(default=Decimal(3), gt=0, le=100)
    max_drawdown_pct: Decimal = Field(default=Decimal(20), gt=0, lt=100)
    reject_streak_threshold: int = Field(default=5, gt=1)

    # Promotion gate input (spec 08): live trading refuses to start unless
    # this is explicitly true in validated config.
    live_enabled: bool = False
