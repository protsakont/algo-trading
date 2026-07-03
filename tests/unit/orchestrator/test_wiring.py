"""Composition root skeleton (specs 01/08).

M1 scope: the AppGraph container exists and holds one instance per core
Protocol; build_graph validates settings and fails loudly until adapters land
in M2+. Full graph construction from config/example.yaml is a spec 08 task.
"""

from dataclasses import FrozenInstanceError, fields

import pytest

from algotrade.config import AppSettings
from algotrade.domain.errors import ConfigError
from algotrade.orchestrator.wiring import AppGraph, build_graph
from tests import fakes


def make_graph() -> AppGraph:
    return AppGraph(
        feed=fakes.FakeDataFeed(),
        feature_store=fakes.FakeFeatureStore(),
        strategy=fakes.AlwaysFlatStrategy(),
        risk=fakes.ApproveAllRiskChecker(),
        sizer=fakes.FixedFractionSizer(),
        gateway=fakes.RecordingBrokerGateway(),
        alerts=fakes.RecordingAlertSink(),
    )


class TestAppGraph:
    def test_holds_one_dependency_per_core_protocol(self) -> None:
        graph = make_graph()
        assert {f.name for f in fields(graph)} == {
            "feed",
            "feature_store",
            "strategy",
            "risk",
            "sizer",
            "gateway",
            "alerts",
        }

    def test_graph_is_immutable(self) -> None:
        graph = make_graph()
        with pytest.raises(FrozenInstanceError):
            graph.risk = fakes.RejectAllRiskChecker()  # type: ignore[misc]


class TestBuildGraph:
    def test_no_adapters_yet_fails_with_config_error(self) -> None:
        with pytest.raises(ConfigError, match="adapter"):
            build_graph(AppSettings())
