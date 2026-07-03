# 06 — Execution Module (Execution Agent)

## Responsibility
แปลง approved signal → order lifecycle จนจบ ผ่าน `BrokerGateway` — ไม่ตัดสินใจเชิงกลยุทธ์ ไม่ข้าม risk

## Flow (บังคับ)
```
Signal → PositionSizer → Order(draft) → RiskChecker.check()
   ├─ rejected → log + metric, จบ
   └─ approved → BrokerGateway.submit() → track lifecycle → reconcile fill → update positions
```

## Scope
- `ExecutionService(sizer, risk, gateway, alerts)`
- Order state machine: DRAFT → SUBMITTED → PARTIALLY_FILLED → FILLED | CANCELLED | REJECTED | EXPIRED — transition นอกตาราง = raise
- Idempotency: client_order_id deterministic (hash signal+timestamp) — retry ไม่ duplicate
- Retry: network error → exponential backoff สูงสุด N ครั้ง; broker reject → ไม่ retry, alert
- Adapters: `PaperGateway` (M5) ก่อน แล้ว live adapter ผ่าน NautilusTrader — สลับด้วย config เท่านั้น

## Requirements
**P0**
- [ ] ExecutionService + state machine + unit tests ทุก transition
- [ ] PaperGateway (fill model เดียวกับ backtest)
- [ ] Idempotent submit (test: submit ซ้ำ → order เดียว)
**P1** — TWAP/iceberg splitting
**P2** — smart order routing

## Acceptance Criteria
- ไม่มี code path เรียก `gateway.submit` โดยไม่ผ่าน `risk.check` — ตรวจทั้ง test + review checklist
- Given timeout แล้ว retry แต่ order เดิม filled แล้ว, Then ไม่เกิด duplicate (idempotency test)
- Given partial fill แล้ว cancel, Then position สะท้อนเฉพาะส่วนที่ fill
- Coverage โมดูล ≥ 85%
