# 04 — Backtest Module (Backtest & Validation Agent)

## Responsibility
รัน strategy ผ่าน NautilusTrader event-driven engine + validation ป้องกัน overfitting — ผู้ออกใบเบิกทางเข้า paper trade

## Scope
- Adapter: DTO/Strategy ของเรา ↔ NautilusTrader — mapping อยู่ที่นี่ที่เดียว
- Fill model: slippage + commission ตาม config ต่อ market — ประกาศ assumption ใน report เสมอ
- Walk-forward: rolling train/test folds ตาม config; รายงานต่อ fold
- Report: `BacktestReport` DTO → JSON + markdown ใน `reports/`

## Requirements
**P0**
- [ ] `BacktestRunner`: (strategy_id, universe, period, config) → `BacktestReport`
- [ ] Metrics: total return, CAGR, Sharpe, Sortino, MaxDD, turnover, win rate, exposure, trade count
- [ ] Reproducibility: same config + data + seed = identical metrics (มี test)
- [ ] Walk-forward runner + per-fold report
**P1**
- [ ] Monte Carlo trade-order resampling → distribution ของ MaxDD
- [ ] Parameter sensitivity heatmap (VectorBT layer สำหรับ sweep)
**P2** — latency modeling, order book replay

## Acceptance Criteria
- Given baseline SMA + fixture data, When backtest, Then จบไม่มี error, report ครบทุก metric
- Given strategy ที่แอบใช้ future data (fixture จงใจ), When lookahead detector, Then ถูกจับได้
- CLI: `algotrade backtest run --strategy sma_cross --config <path>` ทำงาน end-to-end
