"""RiskCheckerChain (spec 05): fail-fast ordering, reject-streak breaker,
default-deny on internal failure, and RiskChecker protocol conformance."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from algotrade.domain.dto import Order, RiskVerdict
from algotrade.domain.enums import OrderSide, OrderType
from algotrade.interfaces import RiskChecker
from algotrade.risk.chain import RiskCheckerChain, build_risk_checker
from algotrade.risk.config import RiskConfig
from algotrade.risk.halt import FileHaltStore
from algotrade.risk.state import AccountSnapshot, AccountStateProvider
from tests.fakes import RecordingAlertSink

TS = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


def make_order(qty: str = "10", side: OrderSide = OrderSide.BUY) -> Order:
    return Order(
        client_order_id="t-1",
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        created_at=TS,
    )


class StaticProvider:
    def __init__(self, snapshot: AccountSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> AccountSnapshot:
        return self._snapshot


class ExplodingProvider:
    def snapshot(self) -> AccountSnapshot:
        raise RuntimeError("account service down")


def healthy_snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        timestamp=TS,
        equity=Decimal("100000"),
        day_start_equity=Decimal("100000"),
        daily_pnl=Decimal("0"),
        high_water_mark=Decimal("100000"),
        last_prices={"AAPL": Decimal("100")},
    )


def make_chain(
    tmp_path: Path,
    snapshot: AccountSnapshot | None = None,
    config: RiskConfig | None = None,
    provider: AccountStateProvider | None = None,
) -> tuple[RiskCheckerChain, FileHaltStore, RecordingAlertSink]:
    halt = FileHaltStore(tmp_path / "halt.json")
    alerts = RecordingAlertSink()
    chain = build_risk_checker(
        config=config or RiskConfig(),
        provider=provider or StaticProvider(snapshot or healthy_snapshot()),
        halt=halt,
        alerts=alerts,
    )
    return chain, halt, alerts


class TestProtocol:
    def test_chain_satisfies_risk_checker_protocol(self, tmp_path: Path) -> None:
        chain, _, _ = make_chain(tmp_path)
        assert isinstance(chain, RiskChecker)

    def test_check_never_raises_returns_verdict(self, tmp_path: Path) -> None:
        chain, _, _ = make_chain(tmp_path, provider=ExplodingProvider())
        verdict = chain.check(make_order(), [])
        assert isinstance(verdict, RiskVerdict)


class TestFailFast:
    def test_healthy_order_passes_all_checks(self, tmp_path: Path) -> None:
        chain, _, _ = make_chain(tmp_path)
        verdict = chain.check(make_order("10"), [])
        assert verdict.approved
        assert verdict.check_name == "RiskCheckerChain"

    def test_first_failing_check_is_the_verdict(self, tmp_path: Path) -> None:
        """Halted + fat-fingered order: HaltStateCheck runs first, so its
        verdict is returned (fail-fast, spec 05)."""
        chain, halt, _ = make_chain(tmp_path)
        halt.halt("manual")
        verdict = chain.check(make_order("99999"), [])
        assert not verdict.approved
        assert verdict.check_name == "HaltStateCheck"

    def test_fat_finger_caught_when_not_halted(self, tmp_path: Path) -> None:
        chain, _, _ = make_chain(tmp_path)
        verdict = chain.check(make_order("99999"), [])
        assert not verdict.approved
        assert verdict.check_name == "MaxOrderSizeCheck"


class TestDefaultDeny:
    def test_provider_failure_rejects_with_reason(self, tmp_path: Path) -> None:
        """Never silently swallow: the verdict says WHY, and it is a reject."""
        chain, _, _ = make_chain(tmp_path, provider=ExplodingProvider())
        verdict = chain.check(make_order(), [])
        assert not verdict.approved
        assert "default-deny" in verdict.reason


class TestRejectStreakBreaker:
    def test_consecutive_rejects_trip_the_halt(self, tmp_path: Path) -> None:
        """Spec 05: error-rate breaker - N consecutive rejects -> halt."""
        config = RiskConfig(reject_streak_threshold=3)
        chain, halt, alerts = make_chain(tmp_path, config=config)

        for _ in range(3):
            assert not chain.check(make_order("99999"), []).approved

        assert halt.is_halted()
        assert "consecutive" in (halt.reason() or "")
        assert any(severity == "CRITICAL" for severity, _ in alerts.alerts)

    def test_approval_resets_the_streak(self, tmp_path: Path) -> None:
        config = RiskConfig(reject_streak_threshold=3)
        chain, halt, _ = make_chain(tmp_path, config=config)

        for _ in range(2):
            chain.check(make_order("99999"), [])
        chain.check(make_order("10"), [])  # approved - resets
        for _ in range(2):
            chain.check(make_order("99999"), [])

        assert not halt.is_halted()


class TestLimitLogging:
    def test_active_limits_are_logged_at_construction(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec 05: log limit values at startup."""
        make_chain(tmp_path)
        output = capsys.readouterr()
        combined = output.out + output.err
        assert "max_position_pct" in combined
        assert "risk_limits_active" in combined


class TestBookkeepingNeverRaises:
    def test_halt_store_failure_during_streak_still_returns_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """qa MUST-3: streak/halt bookkeeping does file I/O; its failure must
        not turn a safe rejection into a raw exception in the order path."""
        config = RiskConfig(reject_streak_threshold=2)
        chain, halt, _ = make_chain(tmp_path, config=config)

        def explode(reason: str) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(halt, "halt", explode)
        chain.check(make_order("99999"), [])  # streak 1
        verdict = chain.check(make_order("99999"), [])  # streak 2 -> halt() raises
        assert isinstance(verdict, RiskVerdict)
        assert not verdict.approved


class TestDrawdownCloseOnly:
    def breached_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            timestamp=TS,
            equity=Decimal("70000"),
            day_start_equity=Decimal("70000"),
            daily_pnl=Decimal("0"),
            high_water_mark=Decimal("100000"),
            last_prices={"AAPL": Decimal("100")},
        )

    def test_de_risking_stays_possible_during_drawdown_breach(self, tmp_path: Path) -> None:
        """qa MUST-4: a 30% drawdown must not trap positions - a pure reduce
        passes the FULL chain even after the halt tripped."""
        from algotrade.domain.dto import Position

        chain, halt, _ = make_chain(tmp_path, snapshot=self.breached_snapshot())
        held = [Position(symbol="AAPL", quantity=Decimal("50"), avg_entry_price=Decimal("100"))]

        first = chain.check(make_order("10", side=OrderSide.SELL), held)
        assert first.approved, first.reason
        assert halt.is_halted()  # breach tripped the persisted halt

        again = chain.check(make_order("10", side=OrderSide.SELL), held)
        assert again.approved, again.reason

    def test_exposure_increase_rejected_during_breach(self, tmp_path: Path) -> None:
        chain, _, _ = make_chain(tmp_path, snapshot=self.breached_snapshot())
        verdict = chain.check(make_order("10", side=OrderSide.BUY), [])
        assert not verdict.approved

    def test_breach_alert_fires_once_not_per_order(self, tmp_path: Path) -> None:
        from algotrade.domain.dto import Position

        chain, _, alerts = make_chain(tmp_path, snapshot=self.breached_snapshot())
        held = [Position(symbol="AAPL", quantity=Decimal("50"), avg_entry_price=Decimal("100"))]
        for _ in range(3):
            chain.check(make_order("5", side=OrderSide.SELL), held)
        critical = [m for severity, m in alerts.alerts if severity == "CRITICAL"]
        assert len(critical) == 1


class TestCompositionEnforcement:
    def test_chain_without_halt_gate_first_is_rejected(self, tmp_path: Path) -> None:
        """qa SHOULD-5 / rule 4: veto ordering is structural, not convention."""
        from algotrade.domain.errors import ConfigError
        from algotrade.risk.checks import MaxOrderSizeCheck

        with pytest.raises(ConfigError, match="HaltStateCheck"):
            RiskCheckerChain(
                checks=[MaxOrderSizeCheck(RiskConfig())],
                provider=StaticProvider(healthy_snapshot()),
                halt=FileHaltStore(tmp_path / "halt.json"),
                alerts=RecordingAlertSink(),
                reject_streak_threshold=5,
            )
