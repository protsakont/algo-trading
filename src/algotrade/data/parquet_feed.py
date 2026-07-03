"""ParquetDataFeed (spec 02): the DataFeed implementation over local parquet
partitions written by the ingest job."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl

from algotrade.data.storage import partition_path
from algotrade.domain.dto import Bar
from algotrade.domain.errors import DataFeedError


def _parse_bound(value: str, name: str) -> datetime:
    """Parse an ISO bound and normalize to UTC — partition selection by year
    must use UTC, or bars near year boundaries silently vanish."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DataFeedError(f"{name} {value!r} is not an ISO date/datetime") from exc
    aware = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return aware.astimezone(UTC)


class ParquetDataFeed:
    """Reads bars from ``root/<symbol>/<timeframe>/<year>.parquet``.

    The [start, end] interval is closed on both ends; date-only strings are
    interpreted as UTC midnight.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def get_bars(self, symbol: str, start: str, end: str, timeframe: str) -> list[Bar]:
        start_ts = _parse_bound(start, "start")
        end_ts = _parse_bound(end, "end")
        if start_ts > end_ts:
            raise DataFeedError(f"start {start!r} is after end {end!r}")

        paths = [
            path
            for year in range(start_ts.year, end_ts.year + 1)
            if (path := partition_path(self._root, symbol, timeframe, year)).exists()
        ]
        if not paths:
            return []

        try:
            frame = (
                pl.concat(pl.read_parquet(p) for p in paths)
                .filter(pl.col("timestamp").is_between(start_ts, end_ts, closed="both"))
                .sort("timestamp")
            )
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise DataFeedError(
                f"failed reading partitions for {symbol}/{timeframe}: {exc}"
            ) from exc

        return [
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=row["timestamp"],
                open=self._decimal(row["open"]),
                high=self._decimal(row["high"]),
                low=self._decimal(row["low"]),
                close=self._decimal(row["close"]),
                volume=self._decimal(row["volume"]),
            )
            for row in frame.to_dicts()
        ]

    @staticmethod
    def _decimal(value: object) -> Decimal:
        """Strip storage-scale trailing zeros without ever producing exponent
        notation (Decimal('1000').normalize() would give Decimal('1E+3'))."""
        if not isinstance(value, Decimal):
            raise DataFeedError(f"stored price has non-Decimal type {type(value).__name__}")
        if value == value.to_integral_value():
            return value.quantize(Decimal(1))
        return value.normalize()
