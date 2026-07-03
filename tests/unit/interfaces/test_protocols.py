"""Core contracts (spec 01): each Protocol exists, is runtime-checkable, and
the central fakes structurally satisfy it."""

import pytest

from algotrade.interfaces import (
    AlertSink,
    BrokerGateway,
    DataFeed,
    FeatureStore,
    PositionSizer,
    RiskChecker,
    Strategy,
)
from tests import fakes

# Typed bindings: mypy (which checks tests/ in CI) fails here if a fake stops
# matching a Protocol *signature* — isinstance below only detects missing names.
_feed: DataFeed = fakes.FakeDataFeed()
_features: FeatureStore = fakes.FakeFeatureStore()
_strategy: Strategy = fakes.AlwaysFlatStrategy()
_risk: RiskChecker = fakes.ApproveAllRiskChecker()
_risk_reject: RiskChecker = fakes.RejectAllRiskChecker()
_sizer: PositionSizer = fakes.FixedFractionSizer()
_gateway: BrokerGateway = fakes.RecordingBrokerGateway()
_alerts: AlertSink = fakes.RecordingAlertSink()

PROTOCOL_TO_FAKE = [
    (DataFeed, fakes.FakeDataFeed()),
    (FeatureStore, fakes.FakeFeatureStore()),
    (Strategy, fakes.AlwaysFlatStrategy()),
    (RiskChecker, fakes.ApproveAllRiskChecker()),
    (PositionSizer, fakes.FixedFractionSizer()),
    (BrokerGateway, fakes.RecordingBrokerGateway()),
    (AlertSink, fakes.RecordingAlertSink()),
]


@pytest.mark.parametrize(
    ("protocol", "fake"),
    PROTOCOL_TO_FAKE,
    ids=[p.__name__ for p, _ in PROTOCOL_TO_FAKE],
)
def test_fake_satisfies_protocol(protocol: type, fake: object) -> None:
    assert isinstance(fake, protocol), (
        f"{type(fake).__name__} no longer satisfies {protocol.__name__} — "
        "a Protocol signature changed; see the escalation rules before proceeding"
    )


def test_protocols_stay_small() -> None:
    """CLAUDE.md rule 2: every Protocol has <= 5 methods."""
    for protocol, _ in PROTOCOL_TO_FAKE:
        methods = [
            name
            for name in vars(protocol)
            if not name.startswith("_") and callable(getattr(protocol, name))
        ]
        assert len(methods) <= 5, f"{protocol.__name__} has {len(methods)} methods: {methods}"
