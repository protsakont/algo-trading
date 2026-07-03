"""Fail-fast risk chain (spec 05) implementing the RiskChecker protocol.

- checks run in a fixed order; the first rejection is the verdict
- N consecutive rejections trip the persisted halt (error-rate breaker)
- ANY internal failure (state provider down, check bug) rejects: default-deny
- active limits are logged at construction (spec 05 startup rule)
"""

from typing import Protocol

import structlog

from algotrade.domain.dto import Order, Position, RiskVerdict
from algotrade.domain.errors import ConfigError
from algotrade.interfaces import AlertSink
from algotrade.risk.checks import (
    DailyLossCircuitBreaker,
    DrawdownCircuitBreaker,
    HaltStateCheck,
    MaxGrossExposureCheck,
    MaxOrderSizeCheck,
    MaxPositionCheck,
)
from algotrade.risk.config import RiskConfig
from algotrade.risk.halt import FileHaltStore
from algotrade.risk.state import AccountSnapshot, AccountStateProvider

_logger = structlog.get_logger(__name__)


class _Check(Protocol):
    name: str

    def evaluate(
        self, order: Order, positions: list[Position], snapshot: AccountSnapshot
    ) -> RiskVerdict: ...


class RiskCheckerChain:
    name = "RiskCheckerChain"

    def __init__(
        self,
        checks: list[_Check],
        provider: AccountStateProvider,
        halt: FileHaltStore,
        alerts: AlertSink,
        reject_streak_threshold: int,
    ) -> None:
        if not checks or not isinstance(checks[0], HaltStateCheck):
            # Rule 4: the veto ordering is enforced structurally, not by
            # convention - a chain without the halt gate first is invalid.
            raise ConfigError("RiskCheckerChain requires HaltStateCheck as the first check")
        self._checks = checks
        self._provider = provider
        self._halt = halt
        self._alerts = alerts
        self._streak_threshold = reject_streak_threshold
        self._reject_streak = 0

    def check(self, order: Order, positions: list[Position]) -> RiskVerdict:
        try:
            verdict = self._run_checks(order, positions)
        except Exception:
            _logger.exception(
                "risk_chain_internal_error",
                client_order_id=order.client_order_id,
                symbol=order.symbol,
            )
            verdict = RiskVerdict(
                approved=False,
                reason="internal risk failure - rejecting (default-deny)",
                check_name=self.name,
            )
        try:
            self._track_streak(verdict)
        except Exception:
            # Streak/halt bookkeeping does file I/O; its failure must never
            # convert a safe rejection into a raw exception in the order path.
            _logger.exception("risk_streak_tracking_failed", check_name=verdict.check_name)
        return verdict

    def _run_checks(self, order: Order, positions: list[Position]) -> RiskVerdict:
        snapshot = self._provider.snapshot()
        for check in self._checks:
            verdict = check.evaluate(order, positions, snapshot)
            if not verdict.approved:
                _logger.info(
                    "order_rejected",
                    check=verdict.check_name,
                    reason=verdict.reason,
                    client_order_id=order.client_order_id,
                )
                return verdict
        return RiskVerdict(approved=True, reason="all checks passed", check_name=self.name)

    def _track_streak(self, verdict: RiskVerdict) -> None:
        if verdict.approved:
            self._reject_streak = 0
            return
        self._reject_streak += 1
        if self._reject_streak >= self._streak_threshold and not self._halt.is_halted():
            reason = (
                f"{self._reject_streak} consecutive order rejections "
                f"(threshold {self._streak_threshold}) - halting"
            )
            self._halt.halt(reason)
            self._alerts.send("CRITICAL", reason)


def build_risk_checker(
    config: RiskConfig,
    provider: AccountStateProvider,
    halt: FileHaltStore,
    alerts: AlertSink,
) -> RiskCheckerChain:
    """Canonical chain order: halt gate first, breakers next, per-order
    limits last."""
    _logger.info("risk_limits_active", **config.model_dump(mode="json"))
    checks: list[_Check] = [
        HaltStateCheck(halt),
        DrawdownCircuitBreaker(config, halt, alerts),
        DailyLossCircuitBreaker(config),
        MaxOrderSizeCheck(config),
        MaxPositionCheck(config),
        MaxGrossExposureCheck(config),
    ]
    return RiskCheckerChain(
        checks=checks,
        provider=provider,
        halt=halt,
        alerts=alerts,
        reject_streak_threshold=config.reject_streak_threshold,
    )
