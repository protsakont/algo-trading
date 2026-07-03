"""Strategy registry + loader (spec 03).

Strategies register under a string id with their own pydantic config model;
the loader validates raw params against that model before construction, so a
misconfigured strategy fails at load time, never mid-run.

The module-level registry dict is the one deliberate exception to the
no-module-state rule: spec 03 mandates decorator registration, and the dict is
write-once at import time (duplicate ids are rejected).
"""

from collections.abc import Callable, Mapping
from typing import NamedTuple, TypeVar

from pydantic import BaseModel, ValidationError

from algotrade.domain.errors import ConfigError
from algotrade.interfaces import Strategy


class _Entry(NamedTuple):
    strategy_cls: type
    config_cls: type[BaseModel]


_REGISTRY: dict[str, _Entry] = {}

_StrategyT = TypeVar("_StrategyT")


def register_strategy(
    strategy_id: str, *, config: type[BaseModel]
) -> Callable[[type[_StrategyT]], type[_StrategyT]]:
    """Class decorator: ``@register_strategy("sma_cross", config=SmaCrossConfig)``.

    The decorated class must take its validated config instance as the sole
    constructor argument and implement the Strategy protocol.
    """

    def decorate(strategy_cls: type[_StrategyT]) -> type[_StrategyT]:
        if strategy_id in _REGISTRY:
            raise ConfigError(
                f"strategy id {strategy_id!r} is already registered "
                f"by {_REGISTRY[strategy_id].strategy_cls.__name__}"
            )
        if not callable(getattr(strategy_cls, "on_features", None)):
            raise ConfigError(
                f"{strategy_cls.__name__} does not implement the Strategy protocol "
                "(missing callable on_features)"
            )
        _REGISTRY[strategy_id] = _Entry(strategy_cls, config)
        return strategy_cls

    return decorate


def registered_ids() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def build_strategy(strategy_id: str, params: Mapping[str, object]) -> Strategy:
    """Validate params against the strategy's config model and construct it."""
    entry = _REGISTRY.get(strategy_id)
    if entry is None:
        raise ConfigError(f"unknown strategy {strategy_id!r}; registered: {list(registered_ids())}")
    unknown = set(params) - set(entry.config_cls.model_fields)
    if unknown:
        raise ConfigError(
            f"invalid params for strategy {strategy_id!r}: unknown keys {sorted(unknown)} "
            f"(accepted: {sorted(entry.config_cls.model_fields)})"
        )
    try:
        config = entry.config_cls.model_validate(dict(params), strict=False)
    except ValidationError as exc:
        raise ConfigError(f"invalid params for strategy {strategy_id!r}: {exc}") from exc
    # Protocol conformance is enforced at decoration time, so anything in the
    # registry constructs to a Strategy.
    strategy: Strategy = entry.strategy_cls(config)
    return strategy
