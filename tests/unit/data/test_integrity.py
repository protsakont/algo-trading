"""Batch integrity checks (spec 02): monotonic timestamps, no duplicates,
OHLC sanity, gap detection. Failures reject the whole batch; gaps are flagged
but never silently forward-filled."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from algotrade.data.integrity import IssueKind, check_batch

T0 = datetime(2026, 1, 5, tzinfo=UTC)
ONE_DAY = timedelta(days=1)


def make_row(
    ts: datetime,
    open_: str = "100",
    high: str = "105",
    low: str = "99",
    close: str = "104",
    volume: str = "1000",
) -> dict[str, object]:
    return {
        "timestamp": ts,
        "open": Decimal(open_),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "volume": Decimal(volume),
    }


def daily_rows(count: int) -> list[Mapping[str, object]]:
    return [make_row(T0 + i * ONE_DAY) for i in range(count)]


class TestCleanBatch:
    def test_clean_batch_passes(self) -> None:
        report = check_batch("AAPL", "1d", daily_rows(5))
        assert report.passed
        assert report.row_count == 5
        assert report.issues == ()
        assert report.gaps == ()


class TestFailures:
    def test_duplicate_timestamp_fails_batch(self) -> None:
        rows = [*daily_rows(3), make_row(T0 + 2 * ONE_DAY)]
        report = check_batch("AAPL", "1d", rows)
        assert not report.passed
        assert any(i.kind is IssueKind.DUPLICATE_TIMESTAMP for i in report.issues)

    def test_non_monotonic_timestamp_fails_batch(self) -> None:
        rows = [make_row(T0), make_row(T0 + 2 * ONE_DAY), make_row(T0 + ONE_DAY)]
        report = check_batch("AAPL", "1d", rows)
        assert not report.passed
        assert any(i.kind is IssueKind.NON_MONOTONIC_TIMESTAMP for i in report.issues)

    def test_high_below_low_fails_with_symbol_and_timestamp(self) -> None:
        """Spec 02 acceptance: reject batch with error identifying symbol+timestamp."""
        bad_ts = T0 + ONE_DAY
        rows = [make_row(T0), make_row(bad_ts, high="98", low="99")]
        report = check_batch("AAPL", "1d", rows)
        assert not report.passed
        [issue] = [i for i in report.issues if i.kind is IssueKind.OHLC_VIOLATION]
        assert issue.symbol == "AAPL"
        assert issue.timestamp == bad_ts

    def test_close_outside_range_fails(self) -> None:
        rows = [make_row(T0, close="200")]
        report = check_batch("AAPL", "1d", rows)
        assert any(i.kind is IssueKind.OHLC_VIOLATION for i in report.issues)

    def test_missing_field_fails(self) -> None:
        row = make_row(T0)
        del row["close"]
        report = check_batch("AAPL", "1d", [row])
        assert not report.passed
        assert any(i.kind is IssueKind.MISSING_FIELD for i in report.issues)

    def test_float_price_fails_batch(self) -> None:
        """Floats must be converted at the vendor adapter, never accepted here."""
        row = make_row(T0)
        row["close"] = 104.5
        report = check_batch("AAPL", "1d", [row])
        assert not report.passed
        assert any(i.kind is IssueKind.INVALID_VALUE for i in report.issues)

    def test_naive_timestamp_fails_batch(self) -> None:
        row = make_row(T0)
        row["timestamp"] = datetime(2026, 1, 5)  # intentionally naive
        report = check_batch("AAPL", "1d", [row])
        assert not report.passed
        assert any(i.kind is IssueKind.INVALID_VALUE for i in report.issues)

    def test_negative_volume_fails(self) -> None:
        report = check_batch("AAPL", "1d", [make_row(T0, volume="-5")])
        assert any(i.kind is IssueKind.OHLC_VIOLATION for i in report.issues)


class TestGaps:
    def test_gap_is_recorded_but_does_not_fail_batch(self) -> None:
        """Spec 02 acceptance: gap -> recorded in report + downstream sees the
        flag; the batch itself still passes (no silent forward-fill)."""
        rows = [make_row(T0), make_row(T0 + ONE_DAY), make_row(T0 + 8 * ONE_DAY)]
        report = check_batch("AAPL", "1d", rows)
        assert report.passed
        [gap] = report.gaps
        assert gap.after == T0 + ONE_DAY
        assert gap.before == T0 + 8 * ONE_DAY

    def test_weekend_spacing_on_daily_bars_is_not_a_gap(self) -> None:
        friday = datetime(2026, 1, 9, tzinfo=UTC)
        monday = datetime(2026, 1, 12, tzinfo=UTC)
        report = check_batch("AAPL", "1d", [make_row(friday), make_row(monday)])
        assert report.gaps == ()

    def test_unknown_timeframe_skips_gap_detection(self) -> None:
        rows = [make_row(T0), make_row(T0 + 40 * ONE_DAY)]
        report = check_batch("AAPL", "7w", rows)
        assert report.passed
        assert report.gaps == ()


class TestEmptyBatch:
    def test_empty_batch_fails(self) -> None:
        """Default-deny: an empty vendor response is suspicious, not a pass."""
        report = check_batch("AAPL", "1d", [])
        assert not report.passed
        assert any(i.kind is IssueKind.EMPTY_BATCH for i in report.issues)
