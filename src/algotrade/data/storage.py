"""Parquet storage layout (spec 02): one file per symbol/timeframe/year.

Prices are stored as fixed-scale Decimal — never float — and timestamps as
UTC datetimes. A batch write is two-phase (all temp files first, then a
rename-only phase) so a mid-batch failure cannot leave a partially renamed
mix of old and new partitions unreported; temps are cleaned up on failure.
"""

from collections.abc import Sequence
from pathlib import Path

import polars as pl

from algotrade.domain.dto import Bar
from algotrade.domain.errors import DataFeedError

# 38 digits / 12 decimal places comfortably covers any listed price or volume.
PRICE_DTYPE = pl.Decimal(38, 12)

SCHEMA: dict[str, pl.DataType] = {
    "timestamp": pl.Datetime(time_unit="us", time_zone="UTC"),
    "open": PRICE_DTYPE,
    "high": PRICE_DTYPE,
    "low": PRICE_DTYPE,
    "close": PRICE_DTYPE,
    "volume": PRICE_DTYPE,
}


def _safe_component(value: str, name: str) -> str:
    """Symbols/timeframes become path components — refuse anything that could
    escape the storage root (validate-at-boundaries rule)."""
    if not value or value != Path(value).name or value in {".", ".."}:
        raise DataFeedError(f"{name} {value!r} is not a safe path component")
    return value


def partition_path(root: Path, symbol: str, timeframe: str, year: int) -> Path:
    return (
        root
        / _safe_component(symbol, "symbol")
        / _safe_component(timeframe, "timeframe")
        / f"{year}.parquet"
    )


def frame_from_bars(bars: Sequence[Bar]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [b.timestamp for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        },
        schema=SCHEMA,
    ).sort("timestamp")


def write_partitions(
    root: Path,
    symbol: str,
    timeframe: str,
    bars: Sequence[Bar],
    *,
    overwrite: bool = False,
) -> list[Path]:
    """Write bars into year partitions.

    Refuses to clobber existing partitions unless ``overwrite=True`` —
    re-ingesting a sub-range would otherwise silently drop the rest of the
    year (incremental ingest is spec 02 P1).
    """
    if not bars:
        return []
    frame = frame_from_bars(bars)
    parts = frame.with_columns(pl.col("timestamp").dt.year().alias("_year")).partition_by(
        "_year", as_dict=False
    )
    targets = [
        (partition_path(root, symbol, timeframe, int(part["_year"][0])), part.drop("_year"))
        for part in parts
    ]

    if not overwrite:
        existing = [str(path) for path, _ in targets if path.exists()]
        if existing:
            raise DataFeedError(
                f"partitions already exist (pass overwrite=True to replace): {existing}"
            )

    temps: list[tuple[Path, Path]] = []
    try:
        for path, part in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".parquet.tmp")
            part.write_parquet(tmp)
            temps.append((tmp, path))
        for tmp, path in temps:
            tmp.replace(path)
    except (OSError, pl.exceptions.PolarsError) as exc:
        for tmp, _ in temps:
            tmp.unlink(missing_ok=True)
        raise DataFeedError(f"failed writing partitions for {symbol}/{timeframe}: {exc}") from exc
    return [path for path, _ in targets]
