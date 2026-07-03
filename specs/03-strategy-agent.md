# 03 — Strategy Module (Strategy Research Agent)

## Responsibility
บ้านของ strategy ทั้งหมด — แปลง `FeatureSet` → `Signal` เท่านั้น ไม่รู้จัก order, broker, position size

## Scope
- ทุก strategy implement `Strategy` Protocol; ลงทะเบียนผ่าน registry (`@register_strategy("sma_cross")`)
- Strategy config เป็น pydantic model ต่อ strategy — validate ตอน load
- Research workflow: triage ด้วย VectorBT ใน `research/` (นอก src, ไม่ deploy) → ไอเดียที่ผ่านค่อย port เป็น class ใน `src/algotrade/strategy/`

## Requirements
**P0**
- [x] `Signal` DTO: symbol, direction (LONG/SHORT/FLAT), strength [-1,1], timestamp, strategy_id, metadata
- [x] Baseline strategy: SMA crossover (reference implementation + test harness)
- [x] Strategy registry + loader จาก config
- [x] Template + doc "วิธีเพิ่ม strategy ใหม่" (เพิ่มได้โดยแก้ ≤ 2 ไฟล์)
**P1**
- [x] Hypothesis document template ใน `research/` (สมมติฐาน, universe, expected edge, invalidation criteria)

## Acceptance Criteria
- Given features เดียวกัน, When `on_features` ซ้ำ, Then signal เหมือนเดิม (deterministic; random ต้อง seed)
- Strategy ห้าม import จาก `execution/`, `risk/` — บังคับด้วย import-linter rule ใน CI
