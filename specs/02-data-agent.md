# 02 — Data Module (Data Agent)

## Responsibility
ดึง/เก็บ/ทำความสะอาด market data และสร้าง features — source of truth เดียวของข้อมูล ห้ามโมดูลอื่นเรียก vendor ตรง

## Scope
- Ingestion: OHLCV จาก vendor adapter → Parquet (partition: symbol/timeframe/year)
- Cleaning: dedupe, gap detection, corporate action adjustment (equities), outlier flag
- FeatureStore: indicators (vectorized pandas/polars) → `FeatureSet` DTO
- Integrity checks หลัง ingest: monotonic timestamps, no-duplicate, OHLC sanity (low ≤ open,close ≤ high)

## Interfaces
`DataFeed`, `FeatureStore` (specs/01)

## Requirements
**P0**
- [ ] `ParquetDataFeed` + `VendorIngestJob` (vendor ตาม Open Question ใน specs/00)
- [ ] Integrity check report — fail = reject ทั้ง batch (atomic)
- [ ] No lookahead: feature ณ เวลา t ใช้ข้อมูล ≤ t เท่านั้น — มี unit test พิสูจน์ทุก feature
**P1**
- [ ] Incremental ingest
- [ ] Data catalog CLI: `algotrade data ls|verify`
**P2** — tick data, order book snapshots

## Acceptance Criteria
- Given ข้อมูลมี gap, When ingest, Then gap ถูกบันทึกใน report + downstream ได้รับ flag — ไม่ silently forward-fill
- Given bar ที่ high < low, When integrity check, Then reject batch พร้อม error ระบุ symbol+timestamp
- Unit tests ใช้ fixture ใน `tests/fixtures/` — ไม่แตะ network (`-m unit`)
