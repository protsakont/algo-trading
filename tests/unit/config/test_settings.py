"""AppSettings (specs 01/08): paper by default, live requires two explicit flags."""

import pytest

from algotrade.config import AppSettings, load_settings
from algotrade.domain.enums import TradingMode
from algotrade.domain.errors import ConfigError


class TestDefaults:
    def test_defaults_to_paper_mode(self) -> None:
        settings = AppSettings()
        assert settings.trading_mode is TradingMode.PAPER
        assert settings.i_understand_live_trading is False


class TestLiveModeGuard:
    def test_live_without_acknowledgement_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="I_UNDERSTAND_LIVE_TRADING"):
            AppSettings(trading_mode=TradingMode.LIVE)

    def test_live_with_acknowledgement_is_accepted(self) -> None:
        settings = AppSettings(trading_mode=TradingMode.LIVE, i_understand_live_trading=True)
        assert settings.trading_mode is TradingMode.LIVE


class TestEnvLoading:
    def test_reads_trading_mode_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRADING_MODE", "paper")
        assert load_settings().trading_mode is TradingMode.PAPER

    def test_live_env_with_acknowledgement_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRADING_MODE", "live")
        monkeypatch.setenv("I_UNDERSTAND_LIVE_TRADING", "true")
        assert load_settings().trading_mode is TradingMode.LIVE

    def test_live_env_without_flag_maps_to_config_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRADING_MODE", "live")
        monkeypatch.delenv("I_UNDERSTAND_LIVE_TRADING", raising=False)
        with pytest.raises(ConfigError) as exc_info:
            load_settings()
        assert "live" in str(exc_info.value).lower()

    def test_invalid_mode_maps_to_config_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRADING_MODE", "yolo")
        with pytest.raises(ConfigError):
            load_settings()

    def test_settings_are_frozen(self) -> None:
        settings = AppSettings()
        with pytest.raises(ValueError, match="frozen"):
            settings.trading_mode = TradingMode.LIVE  # type: ignore[misc]
