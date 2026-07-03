"""Backtest configuration (spec 04). Every assumption that shapes results
lives here and is echoed verbatim into the report."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from algotrade.data.features import FeatureConfig


class BacktestConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timeframe: str = "1d"
    initial_cash: Decimal = Field(default=Decimal(100_000), gt=0)
    trade_quantity: Decimal = Field(default=Decimal(10), gt=0)
    slippage_bps: Decimal = Field(default=Decimal(5), ge=0)
    commission_bps: Decimal = Field(default=Decimal(10), ge=0)
    periods_per_year: int = Field(default=252, gt=0)
    # Reserved for future stochastic fill models; NO code path consumes
    # randomness today (results are deterministic regardless of this value).
    seed: int = 0
    strategy_params: dict[str, int | float | str | bool] = Field(default_factory=dict)
    features: FeatureConfig = FeatureConfig()

    @field_validator("trade_quantity")
    @classmethod
    def _integral_quantity(cls, value: Decimal) -> Decimal:
        if value != value.to_integral_value():
            raise ValueError(f"trade_quantity must be a whole number of units for v1, got {value}")
        return value
