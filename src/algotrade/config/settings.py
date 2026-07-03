"""Application settings (specs 01/08).

Read from environment variables (and a git-ignored ``.env``). Live trading
requires BOTH ``TRADING_MODE=live`` and ``I_UNDERSTAND_LIVE_TRADING=true`` —
and, beyond config, the orchestrator promotion gates (spec 08).
"""

from typing import Self

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from algotrade.domain.enums import TradingMode
from algotrade.domain.errors import ConfigError


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        frozen=True,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    trading_mode: TradingMode = Field(default=TradingMode.PAPER, validation_alias="TRADING_MODE")
    i_understand_live_trading: bool = Field(
        default=False, validation_alias="I_UNDERSTAND_LIVE_TRADING"
    )

    @model_validator(mode="after")
    def _live_requires_explicit_acknowledgement(self) -> Self:
        if self.trading_mode is TradingMode.LIVE and not self.i_understand_live_trading:
            raise ValueError(
                "TRADING_MODE=live requires I_UNDERSTAND_LIVE_TRADING=true (spec 01). "
                "Live trading is additionally gated by the orchestrator (spec 08)."
            )
        return self


def load_settings() -> AppSettings:
    """Boundary loader: maps pydantic validation failures to ConfigError."""
    try:
        return AppSettings()
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc
