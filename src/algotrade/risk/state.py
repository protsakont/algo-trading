"""Account state consumed by risk checks (spec 05).

The provider is a risk-internal protocol: whoever owns account truth
(execution/monitoring) implements it; risk only reads. Checks treat any
missing piece of state as grounds for rejection (default-deny)."""

from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class AccountSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    equity: Decimal = Field(gt=0)
    day_start_equity: Decimal = Field(gt=0)
    daily_pnl: Decimal
    high_water_mark: Decimal = Field(gt=0)
    last_prices: dict[str, Decimal] = Field(default_factory=dict)


@runtime_checkable
class AccountStateProvider(Protocol):
    def snapshot(self) -> AccountSnapshot: ...
