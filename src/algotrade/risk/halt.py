"""Persisted halt state (spec 05): halting survives restarts and only a
manual reset clears it. Any unreadable/ambiguous state file reads as HALTED —
default-deny protects capital, not uptime."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError


class _HaltState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    halted: bool
    reason: str | None = None


class FileHaltStore:
    """JSON-file-backed halt flag. Writes are atomic (temp + rename).

    SINGLE-WRITER assumption (v1): exactly one process owns this file.
    Concurrent writers would race between read and write; if multi-process
    deployment ever arrives, this needs file locking or a real store."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def is_halted(self) -> bool:
        state = self._read()
        return state.halted if state is not None else True

    def reason(self) -> str | None:
        state = self._read()
        if state is None:
            return "halt state file is unreadable (default-deny)"
        return state.reason

    def halt(self, reason: str) -> None:
        """Idempotent: the FIRST reason is kept — it names the actual trigger.
        A corrupt state file (already halted by default-deny) is repaired with
        this real reason so the trigger isn't lost behind 'unreadable'."""
        state = self._read()
        if state is not None and state.halted:
            return
        self._write(_HaltState(halted=True, reason=reason))

    def reset(self) -> None:
        """Manual operator action only — no code path may call this
        automatically (spec 05: restart stays halted)."""
        self._write(_HaltState(halted=False, reason=None))

    def _read(self) -> _HaltState | None:
        """None means unreadable (missing file is NOT unreadable — it is a
        legitimate fresh state)."""
        if not self._path.exists():
            return _HaltState(halted=False)
        try:
            return _HaltState.model_validate(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValidationError):
            return None

    def _write(self, state: _HaltState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(state.model_dump_json(), encoding="utf-8")
        tmp.replace(self._path)
