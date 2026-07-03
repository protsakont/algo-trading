"""Parquet storage layout (spec 02): one file per symbol/timeframe/year.

Prices are stored as fixed-scale Decimal — never float — and timestamps as
UTC datetimes. A batch write is two-phase: every year is staged to a temp
file first, then renamed into place. A failure while staging leaves the live
partitions wholly untouched (temps are cleaned up). A failure partway through
the rename loop of a multi-year batch can commit some years but not others —
each individual partition is still either its old or its new self (never
half-written), but the batch is not atomic across partitions. Recovery is a
re-run (writes are idempotent by timestamp).
"""

from collections.abc import Sequence
from datetime import datetime
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

    return _atomic_write(targets, symbol, timeframe)


def append_partitions(
    root: Path,
    symbol: str,
    timeframe: str,
    bars: Sequence[Bar],
) -> list[Path]:
    """Merge bars into existing year partitions instead of replacing them
    (incremental ingest, spec 02 P1).

    For each affected year the new rows are unioned with whatever is already
    stored; on a duplicate timestamp the new row wins (a re-fetch corrects a
    prior value). The merged year is written atomically, so a mid-merge
    failure leaves the previous partitions intact.
    """
    if not bars:
        return []
    incoming = frame_from_bars(bars).with_columns(pl.col("timestamp").dt.year().alias("_year"))
    targets: list[tuple[Path, pl.DataFrame]] = []
    for part in incoming.partition_by("_year", as_dict=False):
        year = int(part["_year"][0])
        path = partition_path(root, symbol, timeframe, year)
        new = part.drop("_year")
        if path.exists():
            existing = _read_partition(path, symbol, timeframe)
            merged = (
                pl.concat([existing, new]).unique(subset="timestamp", keep="last").sort("timestamp")
            )
        else:
            merged = new.sort("timestamp")
        targets.append((path, merged))
    return _atomic_write(targets, symbol, timeframe)


def latest_timestamp(root: Path, symbol: str, timeframe: str) -> datetime | None:
    """Newest stored bar timestamp for a series, or None if nothing is stored —
    the cursor an incremental ingest resumes from."""
    series_dir = root / _safe_component(symbol, "symbol") / _safe_component(timeframe, "timeframe")
    if not series_dir.exists():
        return None
    years = [int(p.stem) for p in series_dir.glob("*.parquet") if p.stem.isdigit()]
    if not years:
        return None
    path = partition_path(root, symbol, timeframe, max(years))
    frame = _read_partition(path, symbol, timeframe)
    newest = frame.select(pl.col("timestamp").max()).item()
    return newest if isinstance(newest, datetime) else None


def _read_partition(path: Path, symbol: str, timeframe: str) -> pl.DataFrame:
    try:
        return pl.read_parquet(path)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise DataFeedError(f"failed reading partition {symbol}/{timeframe}: {exc}") from exc


def _atomic_write(
    targets: Sequence[tuple[Path, pl.DataFrame]], symbol: str, timeframe: str
) -> list[Path]:
    """Two-phase write: stage every year to a temp file, then rename-only.
    A failure in either phase cleans up temps and reports, leaving the prior
    partitions untouched."""
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
