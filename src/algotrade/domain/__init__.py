"""Domain layer: DTOs, enums, errors. Pure — imports nothing beyond stdlib + pydantic."""

from .dto import Bar, FeatureSet, Order, OrderResult, Position, RiskVerdict, Signal
from .enums import OrderSide, OrderStatus, OrderType, SignalDirection, TradingMode
from .errors import (
    AlgoTradeError,
    BacktestError,
    BrokerError,
    ConfigError,
    DataFeedError,
    RiskRejected,
)

__all__ = [
    "AlgoTradeError",
    "BacktestError",
    "Bar",
    "BrokerError",
    "ConfigError",
    "DataFeedError",
    "FeatureSet",
    "Order",
    "OrderResult",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Position",
    "RiskRejected",
    "RiskVerdict",
    "Signal",
    "SignalDirection",
    "TradingMode",
]
