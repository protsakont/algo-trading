"""BacktestReport (spec 04): the persisted artifact that orchestrator gates
evaluate (spec 08 — gates read artifacts, never self-reported values).

Every cost assumption (slippage, commission, seed, sizing) is embedded so a
report is meaningless-proof: you cannot read a Sharpe without seeing what
fills produced it.
"""

import hashlib
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from algotrade.backtest.config import BacktestConfig
from algotrade.backtest.metrics import BacktestMetrics

# Same-bar-close execution is an assumption exactly like slippage — declared.
EXECUTION_MODEL = "market orders fill at the same bar's close with zero latency"

_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9._-]")


class BacktestReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_id: str
    symbol: str
    start: datetime
    end: datetime
    config: BacktestConfig
    metrics: BacktestMetrics
    bars_used: int
    execution_model: str = EXECUTION_MODEL

    def _artifact_stem(self) -> str:
        """Filesystem-safe and collision-safe: unsafe chars (e.g. 'BRK/B')
        are replaced, and a config digest keeps two differently-configured
        runs of the same window from overwriting each other."""
        safe_strategy = _UNSAFE_PATH_CHARS.sub("-", self.strategy_id)
        safe_symbol = _UNSAFE_PATH_CHARS.sub("-", self.symbol)
        window = f"{self.start:%Y%m%d}-{self.end:%Y%m%d}"
        digest = hashlib.sha256(self.config.model_dump_json().encode()).hexdigest()[:8]
        return f"{safe_strategy}_{safe_symbol}_{window}_{digest}"

    def write_json(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self._artifact_stem()}.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    def write_markdown(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self._artifact_stem()}.md"
        metric_rows = "\n".join(
            f"| {name} | {value} |" for name, value in self.metrics.model_dump().items()
        )
        assumption_rows = "\n".join(
            f"| {name} | {value} |"
            for name, value in {
                **self.config.model_dump(mode="json"),
                "execution_model": self.execution_model,
            }.items()
        )
        path.write_text(
            f"# Backtest Report — {self.strategy_id} on {self.symbol}\n\n"
            f"Period: {self.start.isoformat()} → {self.end.isoformat()} "
            f"({self.bars_used} bars, timeframe {self.config.timeframe})\n\n"
            f"## Metrics\n\n| metric | value |\n|---|---|\n{metric_rows}\n\n"
            f"## Assumptions (declared, spec 04)\n\n"
            f"| assumption | value |\n|---|---|\n{assumption_rows}\n",
            encoding="utf-8",
        )
        return path
