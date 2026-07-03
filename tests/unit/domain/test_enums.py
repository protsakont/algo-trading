"""Enum contracts referenced across specs 03/06/08."""

from algotrade.domain.enums import OrderStatus, SignalDirection, TradingMode


def test_signal_directions_match_spec_03() -> None:
    assert {d.name for d in SignalDirection} == {"LONG", "SHORT", "FLAT"}


def test_order_status_covers_spec_06_state_machine() -> None:
    expected = {
        "DRAFT",
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELLED",
        "REJECTED",
        "EXPIRED",
    }
    assert {s.name for s in OrderStatus} == expected


def test_trading_modes_are_paper_and_live_only() -> None:
    assert {m.value for m in TradingMode} == {"paper", "live"}
