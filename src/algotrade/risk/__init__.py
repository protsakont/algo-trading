"""Risk Agent (spec 05): independent pre-trade layer. Every order passes
through it — no shortcuts — and it can veto or halt above any strategy."""

from .chain import RiskCheckerChain, build_risk_checker
from .checks import (
    DailyLossCircuitBreaker,
    DrawdownCircuitBreaker,
    HaltStateCheck,
    MaxGrossExposureCheck,
    MaxOrderSizeCheck,
    MaxPositionCheck,
)
from .config import RiskConfig
from .halt import FileHaltStore
from .sizing import (
    FixedFractionConfig,
    FixedFractionSizer,
    VolatilityTargetConfig,
    VolatilityTargetSizer,
)
from .state import AccountSnapshot, AccountStateProvider

__all__ = [
    "AccountSnapshot",
    "AccountStateProvider",
    "DailyLossCircuitBreaker",
    "DrawdownCircuitBreaker",
    "FileHaltStore",
    "FixedFractionConfig",
    "FixedFractionSizer",
    "HaltStateCheck",
    "MaxGrossExposureCheck",
    "MaxOrderSizeCheck",
    "MaxPositionCheck",
    "RiskCheckerChain",
    "RiskConfig",
    "VolatilityTargetConfig",
    "VolatilityTargetSizer",
    "build_risk_checker",
]
