"""Strategy registry + config loader (spec 03): strategies register by id via
decorator; the loader validates params against each strategy's own pydantic
config before construction."""

import pytest
from pydantic import BaseModel, ConfigDict, Field

from algotrade.domain.dto import FeatureSet, Signal
from algotrade.domain.errors import ConfigError
from algotrade.interfaces import Strategy
from algotrade.strategy import registry
from algotrade.strategy.registry import build_strategy, register_strategy, registered_ids


class DummyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    window: int = Field(default=5, gt=0)


class DummyStrategy:
    def __init__(self, config: DummyConfig) -> None:
        self.config = config

    def on_features(self, features: FeatureSet) -> list[Signal]:
        return []


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not pollute the real registry."""
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))


class TestRegistration:
    def test_register_and_build_roundtrip(self) -> None:
        register_strategy("dummy", config=DummyConfig)(DummyStrategy)

        strategy = build_strategy("dummy", {"window": 9})

        assert isinstance(strategy, Strategy)
        assert isinstance(strategy, DummyStrategy)
        assert strategy.config.window == 9

    def test_params_default_when_omitted(self) -> None:
        register_strategy("dummy", config=DummyConfig)(DummyStrategy)
        strategy = build_strategy("dummy", {})
        assert isinstance(strategy, DummyStrategy)
        assert strategy.config.window == 5

    def test_duplicate_id_is_rejected(self) -> None:
        register_strategy("dummy", config=DummyConfig)(DummyStrategy)
        with pytest.raises(ConfigError, match="already registered"):
            register_strategy("dummy", config=DummyConfig)(DummyStrategy)

    def test_registered_ids_lists_known_strategies(self) -> None:
        register_strategy("dummy", config=DummyConfig)(DummyStrategy)
        assert "dummy" in registered_ids()


class TestProtocolEnforcement:
    def test_class_without_on_features_is_rejected_at_registration(self) -> None:
        class NotAStrategy:
            def __init__(self, config: DummyConfig) -> None:
                self.config = config

        with pytest.raises(ConfigError, match="does not implement"):
            register_strategy("broken", config=DummyConfig)(NotAStrategy)


class TestLoaderValidation:
    def test_unknown_id_raises_config_error_naming_known_ids(self) -> None:
        with pytest.raises(ConfigError, match="unknown strategy"):
            build_strategy("does_not_exist", {})

    def test_invalid_params_raise_config_error(self) -> None:
        register_strategy("dummy", config=DummyConfig)(DummyStrategy)
        with pytest.raises(ConfigError, match="dummy"):
            build_strategy("dummy", {"window": -1})

    def test_unknown_params_raise_config_error(self) -> None:
        register_strategy("dummy", config=DummyConfig)(DummyStrategy)
        with pytest.raises(ConfigError, match="dummy"):
            build_strategy("dummy", {"windw": 5})


class TestBuiltins:
    def test_sma_cross_is_registered_by_default(self) -> None:
        assert "sma_cross" in registered_ids()
