"""Incremental ingest (spec 02 P1): re-running ingest fetches only bars newer
than what is already stored and merges them into the existing year partitions
without rewriting history. The boundary bar (re-fetched) is deduped, a failing
batch leaves stored data untouched, and an empty response over a populated store
is a successful no-op (already up to date)."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from algotrade.data.ingest import VendorIngestJob
from algotrade.data.parquet_feed import ParquetDataFeed
from algotrade.data.storage import append_partitions, latest_timestamp, write_partitions
from algotrade.domain.dto import Bar

T0 = datetime(2026, 1, 5, tzinfo=UTC)
ONE_DAY = timedelta(days=1)
END = "2026-12-31"


def make_row(
    ts: datetime, close: str = "104", high: str = "105", low: str = "99"
) -> dict[str, object]:
    return {
        "timestamp": ts,
        "open": Decimal("100"),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "volume": Decimal("1000"),
    }


def make_bar(ts: datetime, close: str = "104") -> Bar:
    return Bar(
        symbol="AAPL",
        timeframe="1d",
        timestamp=ts,
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


class RangeVendor:
    """Simulates a real vendor: returns rows from an internal dataset whose
    timestamps fall in the requested [start, end] interval, recording the start
    bound of each call so the incremental cursor can be asserted.

    ``exclusive_start`` models a vendor whose lower bound is exclusive — it omits
    the boundary (cursor) bar, which is the case that can silently hide a gap at
    the ingest boundary."""

    def __init__(
        self, rows: Sequence[Mapping[str, object]], *, exclusive_start: bool = False
    ) -> None:
        self.rows = list(rows)
        self.exclusive_start = exclusive_start
        self.calls: list[tuple[str, str, str, str]] = []

    def fetch_bars(
        self, symbol: str, start: str, end: str, timeframe: str
    ) -> list[Mapping[str, object]]:
        self.calls.append((symbol, start, end, timeframe))
        lo = _as_utc(datetime.fromisoformat(start))
        hi = _as_utc(datetime.fromisoformat(end))
        if self.exclusive_start:
            return [r for r in self.rows if lo < _ts(r) <= hi]
        return [r for r in self.rows if lo <= _ts(r) <= hi]


def _ts(row: Mapping[str, object]) -> datetime:
    ts = row["timestamp"]
    assert isinstance(ts, datetime)
    return ts


def _as_utc(value: datetime) -> datetime:
    """Match the feed's bound handling: a date-only string is UTC midnight."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "market-data"


class TestLatestTimestamp:
    def test_none_when_nothing_stored(self, store_root: Path) -> None:
        assert latest_timestamp(store_root, "AAPL", "1d") is None

    def test_returns_max_timestamp_across_years(self, store_root: Path) -> None:
        bars = [make_bar(datetime(2026, 12, 30, tzinfo=UTC) + i * ONE_DAY) for i in range(5)]
        write_partitions(store_root, "AAPL", "1d", bars)  # spans 2026 -> 2027
        assert latest_timestamp(store_root, "AAPL", "1d") == bars[-1].timestamp

    def test_rejects_unsafe_component(self, store_root: Path) -> None:
        from algotrade.domain.errors import DataFeedError

        with pytest.raises(DataFeedError, match="path component"):
            latest_timestamp(store_root, "../etc", "1d")

    def test_corrupt_partition_maps_to_data_feed_error(self, store_root: Path) -> None:
        """A raw polars error reading the cursor partition must not cross the
        module boundary (CLAUDE.md rule 5)."""
        from algotrade.domain.errors import DataFeedError

        write_partitions(store_root, "AAPL", "1d", [make_bar(T0)])
        (store_root / "AAPL" / "1d" / "2026.parquet").write_bytes(b"not parquet")

        with pytest.raises(DataFeedError, match="failed reading partition"):
            latest_timestamp(store_root, "AAPL", "1d")


class TestAppendPartitions:
    def test_merges_new_bars_into_existing_year(self, store_root: Path) -> None:
        write_partitions(store_root, "AAPL", "1d", [make_bar(T0 + i * ONE_DAY) for i in range(3)])
        append_partitions(
            store_root, "AAPL", "1d", [make_bar(T0 + i * ONE_DAY) for i in range(3, 6)]
        )

        loaded = ParquetDataFeed(store_root).get_bars("AAPL", "2026-01-01", END, "1d")
        assert [b.timestamp for b in loaded] == [T0 + i * ONE_DAY for i in range(6)]

    def test_duplicate_timestamp_takes_the_new_value(self, store_root: Path) -> None:
        write_partitions(store_root, "AAPL", "1d", [make_bar(T0, close="100")])
        append_partitions(store_root, "AAPL", "1d", [make_bar(T0, close="103")])

        loaded = ParquetDataFeed(store_root).get_bars("AAPL", "2026-01-01", END, "1d")
        assert [b.close for b in loaded] == [Decimal("103")]

    def test_append_into_empty_store_creates_partition(self, store_root: Path) -> None:
        append_partitions(store_root, "AAPL", "1d", [make_bar(T0)])
        loaded = ParquetDataFeed(store_root).get_bars("AAPL", "2026-01-01", END, "1d")
        assert len(loaded) == 1


class TestIncrementalIngest:
    def test_first_run_writes_all_from_default_start(self, store_root: Path) -> None:
        vendor = RangeVendor([make_row(T0 + i * ONE_DAY) for i in range(5)])
        job = VendorIngestJob(source=vendor, root=store_root)

        result = job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)

        assert result.report.passed
        assert result.rows_written == 5
        assert vendor.calls[0] == ("AAPL", "2026-01-01", END, "1d")

    def test_second_run_fetches_only_from_last_stored(self, store_root: Path) -> None:
        vendor = RangeVendor([make_row(T0 + i * ONE_DAY) for i in range(5)])
        job = VendorIngestJob(source=vendor, root=store_root)
        job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)

        # Newer bars arrive at the vendor; a second run should pick them up.
        vendor.rows += [make_row(T0 + i * ONE_DAY) for i in range(5, 8)]
        result = job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)

        assert result.report.passed
        # Cursor advanced to the last stored bar, not the default start.
        assert vendor.calls[1][1] == (T0 + 4 * ONE_DAY).isoformat()

        loaded = ParquetDataFeed(store_root).get_bars("AAPL", "2026-01-01", END, "1d")
        assert [b.timestamp for b in loaded] == [T0 + i * ONE_DAY for i in range(8)]

    def test_refetched_boundary_bar_is_not_duplicated(self, store_root: Path) -> None:
        vendor = RangeVendor([make_row(T0 + i * ONE_DAY) for i in range(3)])
        job = VendorIngestJob(source=vendor, root=store_root)
        job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)
        job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)  # same data again

        loaded = ParquetDataFeed(store_root).get_bars("AAPL", "2026-01-01", END, "1d")
        assert [b.timestamp for b in loaded] == [T0 + i * ONE_DAY for i in range(3)]

    def test_empty_response_over_populated_store_is_a_noop(self, store_root: Path) -> None:
        vendor = RangeVendor([make_row(T0 + i * ONE_DAY) for i in range(3)])
        job = VendorIngestJob(source=vendor, root=store_root)
        job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)

        vendor.rows = []  # vendor now returns nothing new
        result = job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)

        assert result.report.passed
        assert result.rows_written == 0
        loaded = ParquetDataFeed(store_root).get_bars("AAPL", "2026-01-01", END, "1d")
        assert len(loaded) == 3

    def test_failing_batch_leaves_existing_data_untouched(self, store_root: Path) -> None:
        vendor = RangeVendor([make_row(T0 + i * ONE_DAY) for i in range(3)])
        job = VendorIngestJob(source=vendor, root=store_root)
        job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)

        # A later bar that violates OHLC sanity (high < low) must reject the batch.
        vendor.rows += [make_row(T0 + 3 * ONE_DAY, high="90", low="99")]
        result = job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)

        assert not result.report.passed
        assert result.rows_written == 0
        loaded = ParquetDataFeed(store_root).get_bars("AAPL", "2026-01-01", END, "1d")
        assert [b.timestamp for b in loaded] == [T0 + i * ONE_DAY for i in range(3)]

    def test_empty_response_over_empty_store_is_default_deny(self, store_root: Path) -> None:
        job = VendorIngestJob(source=RangeVendor([]), root=store_root)
        result = job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)
        assert not result.report.passed
        assert not store_root.exists()

    def test_boundary_gap_is_recorded_with_exclusive_vendor(self, store_root: Path) -> None:
        """A gap between stored history and the resumed batch must be recorded
        even when the vendor's lower bound is exclusive and omits the boundary
        bar (spec 02: gaps are recorded, never silently forward-filled)."""
        vendor = RangeVendor(
            [make_row(T0 + i * ONE_DAY) for i in range(3)], exclusive_start=True
        )  # cursor ends at T0+2
        job = VendorIngestJob(source=vendor, root=store_root)
        job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)

        # Resumed batch begins at T0+7 — a 4-day hole after the stored T0+2.
        vendor.rows += [make_row(T0 + i * ONE_DAY) for i in range(7, 10)]
        result = job.run_incremental("AAPL", "1d", default_start="2026-01-01", end=END)

        assert result.report.passed  # a gap is a flag, not a rejection
        assert result.rows_written == 3
        assert len(result.report.gaps) == 1
        gap = result.report.gaps[0]
        assert gap.after == T0 + 2 * ONE_DAY  # last stored bar seeds the span
        assert gap.before == T0 + 7 * ONE_DAY

    def test_append_spanning_year_boundary(self, store_root: Path) -> None:
        """The multi-target atomic append path: a resumed batch straddling a
        year boundary writes both the existing year and a brand-new year."""
        dec31 = datetime(2026, 12, 31, tzinfo=UTC)
        vendor = RangeVendor([make_row(dec31)])
        job = VendorIngestJob(source=vendor, root=store_root)
        job.run_incremental("AAPL", "1d", default_start="2026-12-01", end="2027-12-31")

        vendor.rows += [make_row(dec31 + i * ONE_DAY) for i in range(1, 3)]  # into 2027
        result = job.run_incremental("AAPL", "1d", default_start="2026-12-01", end="2027-12-31")

        assert result.report.passed
        assert (store_root / "AAPL" / "1d" / "2026.parquet").exists()
        assert (store_root / "AAPL" / "1d" / "2027.parquet").exists()
        loaded = ParquetDataFeed(store_root).get_bars("AAPL", "2026-12-01", "2027-12-31", "1d")
        assert [b.timestamp for b in loaded] == [dec31 + i * ONE_DAY for i in range(3)]
