# 01 — Architecture

## Layering
```
┌─ entrypoints/  (CLI, schedulers) ── บาง ๆ: parse args → เรียก service → format output
├─ services/     (application logic ของแต่ละ agent)
├─ domain/       (DTOs, Protocols, enums, pure logic — ห้าม import I/O)
├─ adapters/     (broker gateways, data vendors, storage — implement Protocols)
└─ infra/        (config, logging, DI composition root)
```
กฎ dependency: ชี้เข้าหา `domain` เท่านั้น (`entrypoints → services → domain ← adapters`)
`domain` ห้าม import อะไรนอก stdlib + pydantic

## Project Layout
```
algo-trade/
├── CLAUDE.md
├── pyproject.toml            # uv, ruff, mypy(strict), pytest config
├── specs/
├── .claude/agents/
├── src/algotrade/
│   ├── domain/
│   │   ├── dto.py            # pydantic frozen models
│   │   ├── ports.py          # Protocols ทั้งหมด
│   │   └── enums.py
│   ├── data/                 # spec 02
│   ├── strategy/             # spec 03
│   ├── backtest/             # spec 04
│   ├── risk/                 # spec 05
│   ├── execution/            # spec 06
│   ├── monitoring/           # spec 07
│   └── infra/
│       ├── config.py         # pydantic-settings, อ่าน env
│       └── composition.py    # composition root — ที่เดียวที่ new concrete classes
├── tests/
│   ├── unit/                 # mock ทุก I/O
│   ├── integration/
│   └── conftest.py           # fixtures + fakes กลาง
└── reports/gates/
```

## Core Contracts (`domain/ports.py`) — โครงตั้งต้น
```python
from typing import Protocol
from decimal import Decimal
from .dto import Bar, FeatureSet, Signal, Order, OrderResult, RiskVerdict, Position

class DataFeed(Protocol):
    def get_bars(self, symbol: str, start: str, end: str, timeframe: str) -> list[Bar]: ...

class FeatureStore(Protocol):
    def compute(self, bars: list[Bar]) -> FeatureSet: ...

class Strategy(Protocol):
    """Strategy ทุกตัว implement แค่นี้ — stateless ต่อ call"""
    def on_features(self, features: FeatureSet) -> list[Signal]: ...

class RiskChecker(Protocol):
    """คืน verdict เสมอ — ไม่ throw เพื่อ reject"""
    def check(self, order: Order, positions: list[Position]) -> RiskVerdict: ...

class PositionSizer(Protocol):
    def size(self, signal: Signal, equity: Decimal, positions: list[Position]) -> Decimal: ...

class BrokerGateway(Protocol):
    def submit(self, order: Order) -> OrderResult: ...
    def cancel(self, order_id: str) -> OrderResult: ...
    def positions(self) -> list[Position]: ...

class AlertSink(Protocol):
    def send(self, severity: str, message: str) -> None: ...
```

## DTO Rules
- pydantic v2, `model_config = ConfigDict(frozen=True)` — immutable ข้าม layer
- ราคา/เงิน = `Decimal`; เวลา = timezone-aware UTC `datetime`
- DTO ↔ NautilusTrader objects แปลงกันใน `adapters/` เท่านั้น
- ห้ามใส่ method ที่มี side effect ใน DTO

## Dependency Injection
- Constructor injection ทุก service: `BacktestService(feed: DataFeed, strategy: Strategy, risk: RiskChecker)`
- Composition root เดียวที่ `infra/composition.py` — mapping config → concrete adapters
- Tests inject fakes/mocks ตรง ๆ ไม่ต้องแตะ composition root

## Error Handling
- Adapter แปลง exception ภายนอก → domain exception (`DataFeedError`, `BrokerError`, `RiskRejected`)
- ห้าม `except Exception: pass` — ทุก catch ต้อง log + ตัดสินใจ (retry/halt/alert)
- Entrypoint แปลง domain exception → exit code + human-readable message; ห้าม stack trace ดิบสู่ผู้ใช้

## Config & Secrets
- `pydantic-settings` อ่านจาก env / `.env` (gitignored)
- โหมด `paper|live` เป็น config field เดียว — composition root เลือก adapter ตามนี้
- Live mode ต้องมี explicit flag `I_UNDERSTAND_LIVE_TRADING=true` ซ้ำอีกชั้น
