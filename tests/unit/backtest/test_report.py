"""BacktestReport (spec 04): JSON + markdown artifacts with assumptions
declared alongside metrics."""

import json
from datetime import UTC, datetime
from pathlib import Path

from algotrade.backtest.config import BacktestConfig
from algotrade.backtest.metrics import BacktestMetrics
from algotrade.backtest.report import BacktestReport

START = datetime(2026, 1, 5, tzinfo=UTC)
END = datetime(2026, 3, 31, tzinfo=UTC)


def make_report() -> BacktestReport:
    return BacktestReport(
        strategy_id="sma_cross",
        symbol="AAPL",
        start=START,
        end=END,
        config=BacktestConfig(strategy_params={"fast_window": 10, "slow_window": 30}),
        metrics=BacktestMetrics(
            total_return=0.12,
            cagr=0.3,
            sharpe=1.4,
            sortino=2.0,
            max_drawdown=0.08,
            turnover=3.2,
            win_rate=0.55,
            exposure=0.7,
            trade_count=14,
        ),
        bars_used=60,
    )


class TestJsonArtifact:
    def test_json_roundtrip_preserves_everything(self, tmp_path: Path) -> None:
        report = make_report()
        path = report.write_json(tmp_path / "reports")

        loaded = BacktestReport.model_validate_json(path.read_text(encoding="utf-8"))
        assert loaded == report

    def test_json_declares_cost_assumptions(self, tmp_path: Path) -> None:
        path = make_report().write_json(tmp_path / "reports")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["config"]["slippage_bps"] == "5"
        assert payload["config"]["commission_bps"] == "10"
        assert payload["config"]["seed"] == 0


class TestMarkdownArtifact:
    def test_markdown_contains_all_metrics_and_assumptions(self, tmp_path: Path) -> None:
        path = make_report().write_markdown(tmp_path / "reports")
        text = path.read_text(encoding="utf-8")
        for required in (
            "sma_cross",
            "AAPL",
            "total_return",
            "cagr",
            "sharpe",
            "sortino",
            "max_drawdown",
            "turnover",
            "win_rate",
            "exposure",
            "trade_count",
            "slippage_bps",
            "commission_bps",
            "seed",
        ):
            assert required in text, f"markdown report is missing {required!r}"

    def test_artifact_names_include_strategy_and_symbol(self, tmp_path: Path) -> None:
        json_path = make_report().write_json(tmp_path)
        md_path = make_report().write_markdown(tmp_path)
        assert "sma_cross" in json_path.name and "AAPL" in json_path.name
        assert md_path.suffix == ".md" and json_path.suffix == ".json"
