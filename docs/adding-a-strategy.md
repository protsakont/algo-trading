# Adding a New Strategy

Adding a strategy touches exactly **two files** (spec 03 requirement):

1. **Create the strategy module** — `src/algotrade/strategy/<your_id>.py`
2. **Register the import** — one line in `src/algotrade/strategy/__init__.py`

## 1. The strategy module

Copy this template. The class implements the `Strategy` protocol
(`on_features(FeatureSet) -> list[Signal]`) and takes its validated config as
the sole constructor argument.

```python
from pydantic import BaseModel, ConfigDict, Field

from algotrade.domain.dto import FeatureSet, Signal
from algotrade.domain.enums import SignalDirection

from .registry import register_strategy

STRATEGY_ID = "my_strategy"


class MyStrategyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lookback: int = Field(default=14, gt=0)


@register_strategy(STRATEGY_ID, config=MyStrategyConfig)
class MyStrategy:
    def __init__(self, config: MyStrategyConfig) -> None:
        self._config = config

    def on_features(self, features: FeatureSet) -> list[Signal]:
        value = features.features.get(f"rsi_{self._config.lookback}")
        if value is None:
            return []  # warmup: silence, never a fabricated signal
        ...
        return [Signal(strategy_id=STRATEGY_ID, symbol=features.symbol, ...)]
```

## 2. Register the import

In `src/algotrade/strategy/__init__.py`:

```python
from . import my_strategy  # registers "my_strategy"  # noqa: F401
```

## Rules (enforced by tests and CI)

- **FeatureSet in, Signal out — nothing else.** Strategies never import from
  `execution/` or `risk/` (the architecture test fails the build if you try).
- **Deterministic**: identical features must produce identical signals. If you
  need randomness, seed it from config.
- **Warmup = no signal.** If a required feature is missing, return `[]`.
- **Config-driven**: every tunable is a validated pydantic field — no magic
  numbers in the class. Unknown/typo'd params are rejected at load time.
- **Tests first**: mirror `tests/unit/strategy/test_sma_cross.py` — signal
  directions, strength bounds, warmup silence, determinism, config validation.

## Using it

```python
from algotrade.strategy import build_strategy

strategy = build_strategy("my_strategy", {"lookback": 21})
```

The id string is what backtest configs and the orchestrator reference
(`algotrade backtest run --strategy my_strategy`, spec 04).

## Research first (spec 03 workflow)

Triage ideas with VectorBT in `research/` (outside `src/`, never deployed).
Only ideas that pass triage get ported to a class here — with a hypothesis doc
per spec 03 P1.
