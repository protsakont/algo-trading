"""Composition root (specs 01/08) — the only place concrete adapters are
imported and constructed. Tests bypass this entirely and inject fakes.

The risk veto is enforced here by construction: execution services are only
ever wired with the RiskChecker between them and the BrokerGateway (spec 06
flow). No alternative wiring path may exist.
"""

from dataclasses import dataclass

from algotrade.config import AppSettings
from algotrade.domain.errors import ConfigError
from algotrade.interfaces import (
    AlertSink,
    BrokerGateway,
    DataFeed,
    FeatureStore,
    PositionSizer,
    RiskChecker,
    Strategy,
)


@dataclass(frozen=True)
class AppGraph:
    """The fully-wired object graph: exactly one instance per core Protocol."""

    feed: DataFeed
    feature_store: FeatureStore
    strategy: Strategy
    risk: RiskChecker
    sizer: PositionSizer
    gateway: BrokerGateway
    alerts: AlertSink


def build_graph(settings: AppSettings) -> AppGraph:
    """Map validated settings to concrete adapters.

    No adapters exist yet — they arrive with specs 02-07. Until then this
    fails loudly rather than wiring placeholders that could reach a broker.
    """
    raise ConfigError(
        f"No adapters are implemented yet for trading_mode={settings.trading_mode.value!r}; "
        "graph construction becomes available as specs 02-07 land (see specs/08-orchestrator.md)."
    )
