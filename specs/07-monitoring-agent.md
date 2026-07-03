# 07 — Monitoring Module (Monitoring & Ops Agent)

## Responsibility
สังเกตการณ์ทั้งระบบ: P&L, positions, health, alerts, kill switch + reconciliation กับ broker

## Scope
- Structured logging (JSON) ทุก event: signal, verdict, order transition, fill, error — correlation id ต่อ signal
- Metrics snapshot ราย interval: equity, positions, exposure, daily P&L, data-feed lag, order error rate
- Reconciliation: positions ระบบ vs broker — mismatch = alert CRITICAL + auto-halt (ผ่าน risk halt state, ไม่สร้าง halt ที่สอง)
- AlertSink adapters: console/log (P0), webhook (P1)
- Kill switch: `algotrade halt` → halt state + cancel open orders (close-only); `algotrade resume` ต้อง confirm

## Requirements
**P0**
- [ ] Structured logger + correlation id ตลอด flow
- [ ] Reconciliation service + auto-halt on mismatch
- [ ] Kill switch CLI + test ว่ามีผลกับ ExecutionService ทันที
- [ ] Daily summary report (markdown → `reports/daily/`)
**P1** — webhook alert, heartbeat monitor (feed เงียบเกิน N นาที → alert)
**P2** — web dashboard

## Acceptance Criteria
- Given position mismatch, When reconcile, Then halt ภายใน 1 cycle + CRITICAL alert ถูกส่ง
- Given `algotrade halt`, Then order เปิดใหม่ถูก reject ตั้งแต่ risk layer (integration test ร่วม 05/06)
- Log ทุกบรรทัด parse เป็น JSON ได้; ห้ามมี secrets ใน log
