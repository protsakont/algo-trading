"""Central fixtures (spec 01). Reusable protocol fakes live in tests/fakes.py."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_trading_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep every test independent of the developer's real trading environment:
    no TRADING_MODE / I_UNDERSTAND_LIVE_TRADING env vars, and no local ``.env``
    (AppSettings resolves ``.env`` relative to cwd, so run from a temp dir)."""
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("I_UNDERSTAND_LIVE_TRADING", raising=False)
    monkeypatch.chdir(tmp_path)
