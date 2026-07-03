"""Halt state (spec 05): persists to disk, survives restart, requires manual
reset, and fails toward halted on any ambiguity (default-deny)."""

from pathlib import Path

import pytest

from algotrade.risk.halt import FileHaltStore


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "halt.json"


class TestLifecycle:
    def test_fresh_store_is_not_halted(self, store_path: Path) -> None:
        assert not FileHaltStore(store_path).is_halted()

    def test_halt_then_query(self, store_path: Path) -> None:
        store = FileHaltStore(store_path)
        store.halt("drawdown breached")
        assert store.is_halted()
        assert "drawdown breached" in (store.reason() or "")

    def test_halt_survives_process_restart(self, store_path: Path) -> None:
        """Spec 05 acceptance: restart -> still halted."""
        FileHaltStore(store_path).halt("daily loss")

        reloaded = FileHaltStore(store_path)  # fresh instance = new process
        assert reloaded.is_halted()
        assert "daily loss" in (reloaded.reason() or "")

    def test_manual_reset_clears_halt(self, store_path: Path) -> None:
        store = FileHaltStore(store_path)
        store.halt("breach")
        store.reset()
        assert not store.is_halted()
        assert not FileHaltStore(store_path).is_halted()  # cleared on disk too

    def test_halt_is_idempotent_and_keeps_first_reason(self, store_path: Path) -> None:
        store = FileHaltStore(store_path)
        store.halt("first breach")
        store.halt("second breach")
        assert "first breach" in (store.reason() or "")


class TestDefaultDeny:
    def test_corrupt_state_file_reads_as_halted(self, store_path: Path) -> None:
        """An unreadable halt file is ambiguous state -> treat as halted."""
        store_path.parent.mkdir(parents=True)
        store_path.write_text("{not json", encoding="utf-8")
        assert FileHaltStore(store_path).is_halted()

    def test_wrong_schema_reads_as_halted(self, store_path: Path) -> None:
        store_path.parent.mkdir(parents=True)
        store_path.write_text('{"unexpected": true}', encoding="utf-8")
        assert FileHaltStore(store_path).is_halted()

    def test_unreadable_state_reason_says_so(self, store_path: Path) -> None:
        store_path.parent.mkdir(parents=True)
        store_path.write_text("{not json", encoding="utf-8")
        assert "unreadable" in (FileHaltStore(store_path).reason() or "")
