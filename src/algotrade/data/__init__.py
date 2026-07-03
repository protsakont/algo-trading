"""Data Agent (spec 02): single source of truth for market data and features.
No other module may call a vendor directly."""

from .features import FeatureConfig, PolarsFeatureStore
from .ingest import IngestResult, VendorIngestJob, VendorSource
from .integrity import GapRecord, IntegrityIssue, IntegrityReport, IssueKind, check_batch
from .parquet_feed import ParquetDataFeed

__all__ = [
    "FeatureConfig",
    "GapRecord",
    "IngestResult",
    "IntegrityIssue",
    "IntegrityReport",
    "IssueKind",
    "ParquetDataFeed",
    "PolarsFeatureStore",
    "VendorIngestJob",
    "VendorSource",
    "check_batch",
]
