"""VendorIngestJob (spec 02): fetch raw rows from a vendor adapter, integrity-
check the batch, and only then write parquet partitions (atomic reject).

``VendorSource`` is a data-module-internal protocol: the concrete vendor
adapter is pending the market/vendor Open Question in specs/00 (see D-006).
"""

from collections.abc import Mapping
from datetime import UTC
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from algotrade.data.integrity import (
    DEFAULT_GAP_TOLERANCE,
    IntegrityReport,
    ParsedRow,
    check_and_parse_batch,
)
from algotrade.data.storage import append_partitions, latest_timestamp, write_partitions
from algotrade.domain.dto import Bar


@runtime_checkable
class VendorSource(Protocol):
    """Raw-row source. Rows use Decimal/int/str values — a vendor adapter must
    convert floats before handing rows over (integrity rejects them)."""

    def fetch_bars(
        self, symbol: str, start: str, end: str, timeframe: str
    ) -> list[Mapping[str, object]]: ...


class IngestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    report: IntegrityReport
    written_paths: tuple[Path, ...] = ()
    rows_written: int = 0


class VendorIngestJob:
    def __init__(
        self,
        source: VendorSource,
        root: Path,
        gap_tolerance: float = DEFAULT_GAP_TOLERANCE,
        overwrite: bool = False,
    ) -> None:
        self._source = source
        self._root = root
        self._gap_tolerance = gap_tolerance
        self._overwrite = overwrite

    def run(self, symbol: str, start: str, end: str, timeframe: str) -> IngestResult:
        raw_rows = self._source.fetch_bars(symbol, start, end, timeframe)
        report, parsed = check_and_parse_batch(
            symbol, timeframe, raw_rows, gap_tolerance=self._gap_tolerance
        )
        if not report.passed:
            return IngestResult(report=report)

        bars = [self._to_bar(symbol, timeframe, row) for row in parsed]
        written = write_partitions(self._root, symbol, timeframe, bars, overwrite=self._overwrite)
        return IngestResult(report=report, written_paths=tuple(written), rows_written=len(bars))

    def run_incremental(
        self, symbol: str, timeframe: str, *, default_start: str, end: str
    ) -> IngestResult:
        """Fetch and merge only bars newer than what is already stored.

        The fetch resumes from the last stored timestamp, passed as the start
        bound. It is treated as inclusive here (the boundary bar is re-fetched
        and the merge dedupes it), but detection of a gap straddling the ingest
        boundary is seeded with the cursor, so a vendor with an *exclusive*
        lower bound that omits the boundary bar still gets the hole recorded.
        When the store is empty the fetch starts at ``default_start``.

        An empty vendor response over a populated store is a successful no-op
        (already up to date); over an empty store it stays default-deny, like a
        full ingest. The no-op is deliberately lenient — an exclusive-bound
        vendor legitimately returns nothing when caught up, so an empty batch is
        not treated as a fault (see D-011).

        ``rows_written`` counts only rows newer than the cursor — genuinely new
        bars — so a re-run that merely re-fetches the boundary reports 0.
        """
        cursor = latest_timestamp(self._root, symbol, timeframe)
        start = cursor.isoformat() if cursor is not None else default_start
        raw_rows = self._source.fetch_bars(symbol, start, end, timeframe)

        if not raw_rows and cursor is not None:
            return IngestResult(
                report=IntegrityReport(symbol=symbol, timeframe=timeframe, row_count=0)
            )

        report, parsed = check_and_parse_batch(
            symbol, timeframe, raw_rows, gap_tolerance=self._gap_tolerance, prev_timestamp=cursor
        )
        if not report.passed:
            return IngestResult(report=report)

        bars = [self._to_bar(symbol, timeframe, row) for row in parsed]
        written = append_partitions(self._root, symbol, timeframe, bars)
        new_rows = sum(1 for bar in bars if cursor is None or bar.timestamp > cursor)
        return IngestResult(report=report, written_paths=tuple(written), rows_written=new_rows)

    @staticmethod
    def _to_bar(symbol: str, timeframe: str, row: ParsedRow) -> Bar:
        return Bar(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=row.timestamp.astimezone(UTC),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
