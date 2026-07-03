"""Batch integrity checks run on raw vendor rows BEFORE Bar DTOs exist (spec 02).

A failing report rejects the whole batch (atomic — the ingest job writes
nothing). Gaps are recorded and flagged downstream, never silently
forward-filled, and do not fail the batch by themselves.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum, unique
from itertools import pairwise

from pydantic import BaseModel, ConfigDict

REQUIRED_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")

# Expected spacing between consecutive bars per timeframe.
TIMEFRAME_DELTAS: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}

# A spacing above tolerance * expected delta is recorded as a gap. 3.0 keeps a
# Fri->Mon weekend on daily bars quiet while flagging anything longer.
DEFAULT_GAP_TOLERANCE = 3.0


@unique
class IssueKind(StrEnum):
    EMPTY_BATCH = "empty_batch"
    MISSING_FIELD = "missing_field"
    INVALID_VALUE = "invalid_value"
    DUPLICATE_TIMESTAMP = "duplicate_timestamp"
    NON_MONOTONIC_TIMESTAMP = "non_monotonic_timestamp"
    OHLC_VIOLATION = "ohlc_violation"


class IntegrityIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: IssueKind
    symbol: str
    timestamp: datetime | None = None
    detail: str


class GapRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    after: datetime
    before: datetime
    span: timedelta


class IntegrityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    row_count: int
    issues: tuple[IntegrityIssue, ...] = ()
    gaps: tuple[GapRecord, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.issues


class ParsedRow(BaseModel):
    """A raw vendor row after validation — what the ingest job builds Bars
    from, so rows are parsed exactly once."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


def _parse_price(value: object) -> Decimal:
    """Decimal/int/str only. Floats must be converted at the vendor adapter —
    accepting them here would silently reintroduce float money."""
    if isinstance(value, float):
        raise ValueError("float values are not accepted; convert at the vendor adapter")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"not a valid decimal: {value!r}") from exc
    raise ValueError(f"unsupported price type {type(value).__name__}")


def _parse_row(
    symbol: str, index: int, row: Mapping[str, object]
) -> tuple[ParsedRow | None, list[IntegrityIssue]]:
    issues: list[IntegrityIssue] = []
    missing = [f for f in REQUIRED_FIELDS if f not in row]
    if missing:
        issues.append(
            IntegrityIssue(
                kind=IssueKind.MISSING_FIELD,
                symbol=symbol,
                detail=f"row {index}: missing {missing}",
            )
        )
        return None, issues

    ts = row["timestamp"]
    if not isinstance(ts, datetime) or ts.tzinfo is None:
        issues.append(
            IntegrityIssue(
                kind=IssueKind.INVALID_VALUE,
                symbol=symbol,
                detail=f"row {index}: timestamp must be a timezone-aware datetime, got {ts!r}",
            )
        )
        return None, issues

    values: dict[str, Decimal] = {}
    for field in ("open", "high", "low", "close", "volume"):
        try:
            values[field] = _parse_price(row[field])
        except ValueError as exc:
            issues.append(
                IntegrityIssue(
                    kind=IssueKind.INVALID_VALUE,
                    symbol=symbol,
                    timestamp=ts,
                    detail=f"row {index}: {field}: {exc}",
                )
            )
    if issues:
        return None, issues
    return ParsedRow(timestamp=ts, **values), issues


def _ohlc_issues(symbol: str, row: ParsedRow) -> list[IntegrityIssue]:
    problems: list[str] = []
    if min(row.open, row.high, row.low, row.close) <= 0:
        problems.append("non-positive price")
    if row.high < row.low:
        problems.append(f"high {row.high} < low {row.low}")
    for name in ("open", "close"):
        price: Decimal = getattr(row, name)
        if not (row.low <= price <= row.high):
            problems.append(f"{name} {price} outside [low={row.low}, high={row.high}]")
    if row.volume < 0:
        problems.append(f"negative volume {row.volume}")
    if not problems:
        return []
    return [
        IntegrityIssue(
            kind=IssueKind.OHLC_VIOLATION,
            symbol=symbol,
            timestamp=row.timestamp,
            detail=f"{symbol} @ {row.timestamp.isoformat()}: {'; '.join(problems)}",
        )
    ]


def _find_gaps(
    rows: Sequence[ParsedRow],
    timeframe: str,
    gap_tolerance: float,
    prev_timestamp: datetime | None = None,
) -> tuple[GapRecord, ...]:
    expected = TIMEFRAME_DELTAS.get(timeframe)
    if expected is None:
        return ()
    threshold = expected * gap_tolerance
    gaps: list[GapRecord] = []
    # ``prev_timestamp`` seeds the scan with the last already-stored bar so a
    # gap straddling an incremental ingest boundary is recorded even when the
    # vendor's lower bound is exclusive and omits the boundary bar (spec 02:
    # gaps are recorded, never silently forward-filled).
    boundaries = [prev_timestamp, *(row.timestamp for row in rows)] if prev_timestamp else None
    timestamps = boundaries if boundaries is not None else [row.timestamp for row in rows]
    for previous, current in pairwise(timestamps):
        span = current - previous
        if span > threshold:
            gaps.append(GapRecord(after=previous, before=current, span=span))
    return tuple(gaps)


def check_and_parse_batch(
    symbol: str,
    timeframe: str,
    rows: Sequence[Mapping[str, object]],
    *,
    gap_tolerance: float = DEFAULT_GAP_TOLERANCE,
    prev_timestamp: datetime | None = None,
) -> tuple[IntegrityReport, tuple[ParsedRow, ...]]:
    """Validate a raw vendor batch, returning the parsed rows alongside the
    report. Parsed rows are only meaningful when the report passed.

    ``prev_timestamp`` is the last already-stored bar for the series (incremental
    ingest); it lets gap detection span the ingest boundary, so a hole between
    stored history and the new batch is recorded even when the vendor omits the
    boundary bar."""
    if not rows:
        report = IntegrityReport(
            symbol=symbol,
            timeframe=timeframe,
            row_count=0,
            issues=(
                IntegrityIssue(
                    kind=IssueKind.EMPTY_BATCH,
                    symbol=symbol,
                    detail="vendor returned no rows (default-deny)",
                ),
            ),
        )
        return report, ()

    issues: list[IntegrityIssue] = []
    parsed: list[ParsedRow] = []
    for index, raw in enumerate(rows):
        row, row_issues = _parse_row(symbol, index, raw)
        issues.extend(row_issues)
        if row is not None:
            parsed.append(row)
            issues.extend(_ohlc_issues(symbol, row))

    for previous, current in pairwise(parsed):
        if current.timestamp == previous.timestamp:
            issues.append(
                IntegrityIssue(
                    kind=IssueKind.DUPLICATE_TIMESTAMP,
                    symbol=symbol,
                    timestamp=current.timestamp,
                    detail=f"duplicate bar at {current.timestamp.isoformat()}",
                )
            )
        elif current.timestamp < previous.timestamp:
            issues.append(
                IntegrityIssue(
                    kind=IssueKind.NON_MONOTONIC_TIMESTAMP,
                    symbol=symbol,
                    timestamp=current.timestamp,
                    detail=(
                        f"timestamp {current.timestamp.isoformat()} arrives after "
                        f"{previous.timestamp.isoformat()}"
                    ),
                )
            )

    gaps = _find_gaps(parsed, timeframe, gap_tolerance, prev_timestamp) if not issues else ()
    report = IntegrityReport(
        symbol=symbol,
        timeframe=timeframe,
        row_count=len(rows),
        issues=tuple(issues),
        gaps=gaps,
    )
    return report, tuple(parsed)


def check_batch(
    symbol: str,
    timeframe: str,
    rows: Sequence[Mapping[str, object]],
    *,
    gap_tolerance: float = DEFAULT_GAP_TOLERANCE,
) -> IntegrityReport:
    """Validate a raw vendor batch. Any issue fails the whole batch (atomic);
    gaps are informational flags for downstream consumers."""
    report, _ = check_and_parse_batch(symbol, timeframe, rows, gap_tolerance=gap_tolerance)
    return report
