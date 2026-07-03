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
from algotrade.data.storage import write_partitions
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
