"""VendorIngestJob (spec 02): vendor rows -> integrity check -> parquet.
A failing report rejects the whole batch atomically — nothing is written."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from algotrade.data.ingest import VendorIngestJob
from algotrade.data.parquet_feed import ParquetDataFeed

T0 = datetime(2026, 1, 5, tzinfo=UTC)
ONE_DAY = timedelta(days=1)


def make_row(ts: datetime, high: str = "105", low: str = "99") -> dict[str, object]:
    return {
        "timestamp": ts,
        "open": Decimal("100"),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal("104"),
        "volume": Decimal("1000"),
    }


class StubVendor:
    def __init__(self, rows: Sequence[Mapping[str, object]]) -> None:
        self._rows = list(rows)
        self.calls: list[tuple[str, str, str, str]] = []

    def fetch_bars(
        self, symbol: str, start: str, end: str, timeframe: str
    ) -> list[Mapping[str, object]]:
        self.calls.append((symbol, start, end, timeframe))
        return self._rows


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "market-data"


class TestHappyPath:
    def test_clean_batch_is_written_and_readable(self, store_root: Path) -> None:
        vendor = StubVendor([make_row(T0 + i * ONE_DAY) for i in range(5)])
        job = VendorIngestJob(source=vendor, root=store_root)

        result = job.run("AAPL", "2026-01-01", "2026-01-31", "1d")

        assert result.report.passed
        assert result.rows_written == 5
        assert vendor.calls == [("AAPL", "2026-01-01", "2026-01-31", "1d")]

        feed = ParquetDataFeed(store_root)
        bars = feed.get_bars("AAPL", "2026-01-01", "2026-01-31", "1d")
        assert len(bars) == 5
        assert bars[0].close == Decimal("104")

    def test_gappy_batch_is_written_with_gap_flags(self, store_root: Path) -> None:
        vendor = StubVendor([make_row(T0), make_row(T0 + 10 * ONE_DAY)])
        job = VendorIngestJob(source=vendor, root=store_root)

        result = job.run("AAPL", "2026-01-01", "2026-01-31", "1d")

        assert result.report.passed
        assert len(result.report.gaps) == 1
        assert result.rows_written == 2


class TestAtomicReject:
    def test_failing_batch_writes_nothing(self, store_root: Path) -> None:
        rows = [make_row(T0), make_row(T0 + ONE_DAY, high="98", low="99")]
        job = VendorIngestJob(source=StubVendor(rows), root=store_root)

        result = job.run("AAPL", "2026-01-01", "2026-01-31", "1d")

        assert not result.report.passed
        assert result.rows_written == 0
        assert result.written_paths == ()
        assert not store_root.exists(), "rejected batch must leave no files behind"

    def test_empty_vendor_response_writes_nothing(self, store_root: Path) -> None:
        job = VendorIngestJob(source=StubVendor([]), root=store_root)
        result = job.run("AAPL", "2026-01-01", "2026-01-31", "1d")
        assert not result.report.passed
        assert not store_root.exists()
