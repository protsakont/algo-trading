"""Strategy Agent (spec 03): FeatureSet -> Signal only. Strategies never know
about orders, brokers, positions, or sizing.

Importing this package registers the built-in strategies. Adding a new one
touches exactly two files: the new module + one import line here (see
docs/adding-a-strategy.md).
"""

from . import sma_cross  # registers "sma_cross"  # noqa: F401
from .registry import build_strategy, register_strategy, registered_ids
from .sma_cross import SmaCrossConfig, SmaCrossStrategy

__all__ = [
    "SmaCrossConfig",
    "SmaCrossStrategy",
    "build_strategy",
    "register_strategy",
    "registered_ids",
]
