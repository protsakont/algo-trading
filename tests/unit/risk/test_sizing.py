"""Position sizers (spec 05): volatility targeting default, fixed-fraction
alternative. Missing data sizes to zero (default-deny), never guesses."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from algotrade.domain.dto import Signal
from algotrade.domain.enums import SignalDirection
from algotrade.interfaces import PositionSizer
from algotrade.risk.sizing import (
    FixedFractionConfig,
    FixedFractionSizer,
    VolatilityTargetConfig,
    VolatilityTargetSizer,
)

TS = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
EQUITY = Decimal("100000")


def make_signal(strength: float = 1.0, symbol: str = "AAPL") -> Signal:
    return Signal(
        strategy_id="sma_cross",
        symbol=symbol,
        direction=SignalDirection.LONG if strength >= 0 else SignalDirection.SHORT,
        strength=strength,
        timestamp=TS,
    )


class TestFixedFractionSizer:
    def test_full_strength_sizes_the_configured_fraction(self) -> None:
        sizer = FixedFractionSizer(
            FixedFractionConfig(fraction_pct=Decimal(2)),
            price_lookup={"AAPL": Decimal("100")}.get,
        )
        qty = sizer.size(make_signal(1.0), EQUITY, [])
        assert qty == Decimal(20)  # 2% of 100k = 2000 notional / 100

    def test_strength_scales_the_size(self) -> None:
        sizer = FixedFractionSizer(
            FixedFractionConfig(fraction_pct=Decimal(2)),
            price_lookup={"AAPL": Decimal("100")}.get,
        )
        assert sizer.size(make_signal(0.5), EQUITY, []) == Decimal(10)

    def test_short_signal_sizes_by_absolute_strength(self) -> None:
        sizer = FixedFractionSizer(
            FixedFractionConfig(fraction_pct=Decimal(2)),
            price_lookup={"AAPL": Decimal("100")}.get,
        )
        assert sizer.size(make_signal(-1.0), EQUITY, []) == Decimal(20)

    def test_missing_price_sizes_zero(self) -> None:
        sizer = FixedFractionSizer(FixedFractionConfig(), price_lookup=lambda _: None)
        assert sizer.size(make_signal(), EQUITY, []) == Decimal(0)

    def test_pathological_magnitudes_size_zero_not_explode(self) -> None:
        sizer = FixedFractionSizer(
            FixedFractionConfig(fraction_pct=Decimal(100)),
            price_lookup=lambda _: Decimal("1E-30"),
        )
        assert sizer.size(make_signal(1.0), Decimal("1E+40"), []) == Decimal(0)

    def test_quantity_rounds_down_to_whole_units(self) -> None:
        sizer = FixedFractionSizer(
            FixedFractionConfig(fraction_pct=Decimal(1)),
            price_lookup={"AAPL": Decimal("333")}.get,
        )
        assert sizer.size(make_signal(1.0), EQUITY, []) == Decimal(3)  # 1000/333 = 3.003

    def test_satisfies_position_sizer_protocol(self) -> None:
        sizer = FixedFractionSizer(FixedFractionConfig(), price_lookup=lambda _: None)
        assert isinstance(sizer, PositionSizer)


class TestVolatilityTargetSizer:
    def make_sizer(
        self,
        vol: Decimal | None,
        price: Decimal | None = Decimal("100"),
        target_pct: str = "1",
        cap_pct: str = "10",
    ) -> VolatilityTargetSizer:
        return VolatilityTargetSizer(
            VolatilityTargetConfig(
                target_daily_vol_pct=Decimal(target_pct), max_position_pct=Decimal(cap_pct)
            ),
            price_lookup=lambda _: price,
            volatility_lookup=lambda _: vol,
        )

    def test_sizes_to_hit_the_vol_target(self) -> None:
        """Target 1% daily vol on 100k equity = 1000 risk budget; asset daily
        vol 2% at price 100 -> notional 50k, capped at 10% -> 10k -> 100 sh."""
        sizer = self.make_sizer(vol=Decimal("0.02"))
        assert sizer.size(make_signal(1.0), EQUITY, []) == Decimal(100)

    def test_uncapped_when_vol_is_high(self) -> None:
        # asset vol 20%: notional = 1000/0.2 = 5000 -> 50 shares (under cap)
        sizer = self.make_sizer(vol=Decimal("0.20"))
        assert sizer.size(make_signal(1.0), EQUITY, []) == Decimal(50)

    def test_strength_scales_the_target(self) -> None:
        sizer = self.make_sizer(vol=Decimal("0.20"))
        assert sizer.size(make_signal(0.5), EQUITY, []) == Decimal(25)

    def test_missing_volatility_sizes_zero(self) -> None:
        sizer = self.make_sizer(vol=None)
        assert sizer.size(make_signal(), EQUITY, []) == Decimal(0)

    def test_zero_volatility_sizes_zero_not_infinity(self) -> None:
        sizer = self.make_sizer(vol=Decimal("0"))
        assert sizer.size(make_signal(), EQUITY, []) == Decimal(0)

    def test_missing_price_sizes_zero(self) -> None:
        sizer = self.make_sizer(vol=Decimal("0.02"), price=None)
        assert sizer.size(make_signal(), EQUITY, []) == Decimal(0)

    def test_flat_signal_sizes_zero(self) -> None:
        sizer = self.make_sizer(vol=Decimal("0.02"))
        flat = Signal(
            strategy_id="s",
            symbol="AAPL",
            direction=SignalDirection.FLAT,
            strength=0.0,
            timestamp=TS,
        )
        assert sizer.size(flat, EQUITY, []) == Decimal(0)

    def test_satisfies_position_sizer_protocol(self) -> None:
        assert isinstance(self.make_sizer(vol=Decimal("0.02")), PositionSizer)


class TestConfigValidation:
    def test_fraction_must_be_positive_and_bounded(self) -> None:
        with pytest.raises(ValueError):
            FixedFractionConfig(fraction_pct=Decimal(0))
        with pytest.raises(ValueError):
            FixedFractionConfig(fraction_pct=Decimal(101))

    def test_vol_target_bounds(self) -> None:
        with pytest.raises(ValueError):
            VolatilityTargetConfig(target_daily_vol_pct=Decimal(0))
