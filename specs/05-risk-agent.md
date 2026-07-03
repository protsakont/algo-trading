# 05 — Risk Module (Risk Management Agent)

## Responsibility
Pre-trade risk layer อิสระ — **ทุก order ต้องผ่าน ไม่มีทางลัด** และ veto/halt ได้เหนือทุก strategy

## Scope
- `RiskChecker` chain: fail-fast, verdict มีเหตุผลเสมอ
- `PositionSizer`: volatility targeting เป็น default, fixed-fraction เป็นทางเลือก
- Circuit breakers: daily loss, max drawdown, error-rate (reject ติดกัน N ครั้ง → halt)
- Halt state persist ลง disk — restart แล้วยัง halt, ต้อง manual reset

## Checks (P0 ทั้งหมด)
- [x] MaxPositionCheck — position ต่อ symbol ≤ X% equity
- [x] MaxGrossExposureCheck
- [x] MaxOrderSizeCheck — กัน fat-finger
- [x] DailyLossCircuitBreaker — แตะ limit → reject order เปิดใหม่, อนุญาตเฉพาะ order ลด exposure
- [x] DrawdownCircuitBreaker — ต่ำกว่า HWM เกิน Y% → halt + alert CRITICAL
- [x] HaltStateCheck — halt แล้ว reject ทุกอย่างยกเว้น close-only

## Design Rules
- `RiskVerdict` = {approved, reason, check_name} — ไม่ใช้ exception เป็น control flow
- Risk ห้ามพึ่ง strategy module (ทิศทาง: execution → risk → domain)
- ทุก limit จาก config, default อนุรักษ์นิยม, log ค่าตอน startup
- Ambiguous state (ข้อมูลหาย, position ไม่รู้จัก) = reject (default-deny)

## Acceptance Criteria
- Property-based tests (hypothesis): ไม่มี input ใดทำให้ order เกิน limit ถูก approve
- Given halt state, When restart process, Then ยัง halt (test persist/reload)
- Coverage โมดูล ≥ 85% — CI fail ถ้าต่ำกว่า
