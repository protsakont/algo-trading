"""Backtest Agent (spec 04): NautilusTrader-backed validation pipeline."""

from .config import BacktestConfig
from .lookahead import LookaheadViolation, detect_lookahead, streaming_pipeline
from .metrics import BacktestMetrics, compute_metrics
from .report import BacktestReport
from .runner import BacktestRunner
from .walk_forward import FoldReport, WalkForwardConfig, WalkForwardReport, WalkForwardRunner

__all__ = [
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestReport",
    "BacktestRunner",
    "FoldReport",
    "LookaheadViolation",
    "WalkForwardConfig",
    "WalkForwardReport",
    "WalkForwardRunner",
    "compute_metrics",
    "detect_lookahead",
    "streaming_pipeline",
]
