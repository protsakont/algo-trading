"""Core cross-module contracts (spec 01). Protocols only — no implementations."""

from .protocols import (
    AlertSink,
    BrokerGateway,
    DataFeed,
    FeatureStore,
    PositionSizer,
    RiskChecker,
    Strategy,
)

__all__ = [
    "AlertSink",
    "BrokerGateway",
    "DataFeed",
    "FeatureStore",
    "PositionSizer",
    "RiskChecker",
    "Strategy",
]
