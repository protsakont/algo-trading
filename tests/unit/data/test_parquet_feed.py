"""ParquetDataFeed (spec 02): partitioned symbol/timeframe/year storage,
Decimal-preserving roundtrip, closed [start, end] interval."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from algotrade.data.parquet_feed import ParquetDataFeed
from algotrade.data.storage import write_partitions
from algotrade.domain.dto import Bar
from algotrade.domain.errors import DataFeedError

T0 = datetime(2026, 1, 5, tzinfo=UTC)


def make_bar(ts: datetime, close: str = "104", symbol: str = "AAPL", timeframe: str = "1d") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=ts,
        timeframe=timeframe,
        open=Decimal("100"),
        high=Decimal("105.50"),
        low=Decimal("99.25"),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "market-data"


class TestRoundtrip:
    def test_bars_roundtrip_with_decimal_precision(self, store_root: Path) -> None:
        bars = [make_bar(T0 + timedelta(days=i), close="104.1234") for i in range(3)]
        write_partitions(store_root, "AAPL", "1d", bars)

        feed = ParquetDataFeed(store_root)
        loaded = feed.get_bars("AAPL", "2026-01-01", "2026-12-31", "1d")

        assert loaded == bars
        assert isinstance(loaded[0].close, Decimal)
        assert loaded[0].close == Decimal("104.1234")

    def test_partitions_split_by_year_and_read_across_years(self, store_root: Path) -> None:
        december = datetime(2026, 12, 30, tzinfo=UTC)
        bars = [make_bar(december + timedelta(days=i)) for i in range(5)]  # spans 2026/2027
        write_partitions(store_root, "AAPL", "1d", bars)

        assert (store_root / "AAPL" / "1d" / "2026.parquet").exists()
        assert (store_root / "AAPL" / "1d" / "2027.parquet").exists()

        feed = ParquetDataFeed(store_root)
        loaded = feed.get_bars("AAPL", "2026-12-30", "2027-01-03", "1d")
        assert loaded == bars


class TestFiltering:
    def test_interval_is_closed_on_both_ends(self, store_root: Path) -> None:
        bars = [make_bar(T0 + timedelta(days=i)) for i in range(10)]
        write_partitions(store_root, "AAPL", "1d", bars)

        feed = ParquetDataFeed(store_root)
        loaded = feed.get_bars("AAPL", "2026-01-07", "2026-01-09", "1d")
        assert [b.timestamp.day for b in loaded] == [7, 8, 9]

    def test_bars_come_back_sorted_by_timestamp(self, store_root: Path) -> None:
        bars = [make_bar(T0 + timedelta(days=i)) for i in range(4)]
        write_partitions(store_root, "AAPL", "1d", list(reversed(bars)))

        feed = ParquetDataFeed(store_root)
        loaded = feed.get_bars("AAPL", "2026-01-01", "2026-01-31", "1d")
        assert loaded == bars

    def test_unknown_symbol_returns_empty(self, store_root: Path) -> None:
        write_partitions(store_root, "AAPL", "1d", [make_bar(T0)])
        feed = ParquetDataFeed(store_root)
        assert feed.get_bars("MSFT", "2026-01-01", "2026-12-31", "1d") == []

    def test_timeframes_are_isolated(self, store_root: Path) -> None:
        write_partitions(store_root, "AAPL", "1d", [make_bar(T0)])
        write_partitions(store_root, "AAPL", "1h", [make_bar(T0, timeframe="1h")])

        feed = ParquetDataFeed(store_root)
        loaded = feed.get_bars("AAPL", "2026-01-01", "2026-12-31", "1h")
        assert [b.timeframe for b in loaded] == ["1h"]


class TestTimezoneBounds:
    def test_offset_bounds_still_find_bars_across_year_partitions(self, store_root: Path) -> None:
        """Regression (qa M2): a +05:00 start bound used to select year
        partitions by its LOCAL year, silently skipping the prior year's file
        even though the interval reached into it."""
        bar = make_bar(datetime(2025, 12, 31, 20, 0, tzinfo=UTC))
        write_partitions(store_root, "AAPL", "1d", [bar])

        feed = ParquetDataFeed(store_root)
        loaded = feed.get_bars("AAPL", "2026-01-01T00:00:00+05:00", "2026-06-01", "1d")

        assert loaded == [bar]  # start is 2025-12-31T19:00Z, so the bar is in range


class TestProtocolConformance:
    def test_feed_satisfies_data_feed_protocol(self, store_root: Path) -> None:
        from algotrade.interfaces import DataFeed

        assert isinstance(ParquetDataFeed(store_root), DataFeed)


class TestErrors:
    def test_corrupt_partition_maps_to_data_feed_error(self, store_root: Path) -> None:
        """Regression (qa M3): raw polars exceptions must not cross the module
        boundary (CLAUDE.md rule 5)."""
        write_partitions(store_root, "AAPL", "1d", [make_bar(T0)])
        path = store_root / "AAPL" / "1d" / "2026.parquet"
        path.write_bytes(b"this is not parquet")

        feed = ParquetDataFeed(store_root)
        with pytest.raises(DataFeedError, match="failed reading"):
            feed.get_bars("AAPL", "2026-01-01", "2026-12-31", "1d")

    def test_path_escaping_symbol_is_rejected(self, store_root: Path) -> None:
        feed = ParquetDataFeed(store_root)
        with pytest.raises(DataFeedError, match="path component"):
            feed.get_bars("../../etc", "2026-01-01", "2026-12-31", "1d")

    def test_overwrite_of_existing_partition_is_refused(self, store_root: Path) -> None:
        """Re-ingesting a sub-range must not silently drop the rest of the
        year (incremental ingest is spec 02 P1)."""
        write_partitions(store_root, "AAPL", "1d", [make_bar(T0)])
        with pytest.raises(DataFeedError, match="already exist"):
            write_partitions(store_root, "AAPL", "1d", [make_bar(T0 + timedelta(days=1))])

        replaced = write_partitions(
            store_root, "AAPL", "1d", [make_bar(T0 + timedelta(days=1))], overwrite=True
        )
        assert len(replaced) == 1

    def test_unparseable_date_raises_data_feed_error(self, store_root: Path) -> None:
        feed = ParquetDataFeed(store_root)
        with pytest.raises(DataFeedError, match="not-a-date"):
            feed.get_bars("AAPL", "not-a-date", "2026-12-31", "1d")

    def test_start_after_end_raises_data_feed_error(self, store_root: Path) -> None:
        feed = ParquetDataFeed(store_root)
        with pytest.raises(DataFeedError, match="start"):
            feed.get_bars("AAPL", "2026-12-31", "2026-01-01", "1d")
