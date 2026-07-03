# 00 — Overview

## Problem Statement
ต้องการระบบ algo-trading ที่ (1) วิจัยสัญญาณได้เร็ว (2) validate ด้วย execution realism ก่อนใช้เงินจริง (3) มี risk management เป็น layer อิสระที่ veto ได้เสมอ (4) โค้ด backtest กับ live เป็นชุดเดียวกัน ลด implementation gap

## Goals
1. Pipeline ครบ: `Research → Backtest → Paper → Live` โดยแต่ละ stage มี gate ชัดเจน
2. Strategy ใหม่เพิ่มได้โดย implement interface เดียว (`Strategy`) ไม่แตะ core
3. Risk checks เป็น pre-trade layer อิสระ — ทุก order ผ่าน risk ก่อนถึง broker 100%
4. สลับ paper ↔ live ได้ด้วย config เท่านั้น (zero code change)
5. Test coverage ≥ 85% ใน `src/risk` และ `src/execution` (โมดูลที่พลาดแล้วเสียเงิน)

## Non-Goals (v1)
- ❌ HFT / sub-millisecond latency — สถาปัตยกรรมนี้ไม่ออกแบบเพื่อ colocation
- ❌ Web UI — v1 ใช้ CLI + structured logs + alert; dashboard เป็น P2
- ❌ ML/RL strategies — โครงสร้างรองรับผ่าน `Strategy` interface แต่ไม่ implement ใน v1
- ❌ Multi-broker simultaneous execution — v1 = 1 broker adapter, ออกแบบ interface เผื่อไว้
- ❌ Tax/accounting reporting

## Milestones
| # | Milestone | Deliverable | Gate |
|---|---|---|---|
| M1 | Skeleton + Core contracts | project layout, DTOs, Protocols, DI wiring, CI (pytest+ruff+mypy) | CI เขียว, review ผ่าน |
| M2 | Data layer | ingestion, storage, feature pipeline + tests | ข้อมูล 1 universe ครบ, integrity checks ผ่าน |
| M3 | Backtest harness | NautilusTrader integration, baseline strategy (SMA cross) รันจบ | report reproducible (same seed = same result) |
| M4 | Risk layer | position sizing, limits, circuit breaker + tests | property-based tests ผ่าน, coverage ≥ 85% |
| M5 | Execution + Paper | broker adapter (paper), order lifecycle | paper trade 5 วันทำการโดยไม่มี unhandled error |
| M6 | Monitoring + Live-ready | reconciliation, alerts, kill switch | runbook ครบ, kill switch ทดสอบแล้ว |

## Stage Gates (strategy lifecycle) — บันทึกหลักฐานใน `reports/gates/<strategy>/`
1. **Research → Backtest**: สัญญาณมี edge ใน in-sample (VectorBT triage), hypothesis doc ครบ
2. **Backtest → Paper**: walk-forward OOS Sharpe > 0 ในทุก fold ส่วนใหญ่, MaxDD ภายใน limit ที่ประกาศล่วงหน้า, review ไม่พบ lookahead
3. **Paper → Live**: paper ≥ 20 วันทำการ, slippage จริงต่างจาก backtest assumption ไม่เกิน threshold, risk sign-off
4. **Live**: เริ่มที่ position size ขั้นต่ำ, auto de-risk เมื่อแตะ drawdown limit

## Open Questions
- [ ] **(M2, blocking)** Universe/ตลาดเป้าหมาย: crypto, US equities, TFEX/SET? → กำหนด data source + broker adapter
- [ ] **(M2)** Data vendor + license/cost
- [ ] **(M5, blocking)** Broker สำหรับ paper/live (เลือกจาก adapter ที่ NautilusTrader รองรับ ตามตลาด)
- [ ] **(M4)** Risk limits ตั้งต้น: max position %, vol target, daily loss limit
