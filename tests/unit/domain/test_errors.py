"""Error hierarchy: every domain error is an AlgoTradeError (spec 01)."""

import pytest

from algotrade.domain.errors import (
    AlgoTradeError,
    BacktestError,
    BrokerError,
    ConfigError,
    DataFeedError,
    RiskRejected,
)


@pytest.mark.parametrize(
    "error_type",
    [ConfigError, DataFeedError, BrokerError, RiskRejected, BacktestError],
)
def test_domain_errors_subclass_algotrade_error(error_type: type[Exception]) -> None:
    assert issubclass(error_type, AlgoTradeError), (
        f"{error_type.__name__} must be part of the AlgoTradeError hierarchy "
        "so boundaries can catch one base type"
    )


def test_algotrade_error_carries_message() -> None:
    err = DataFeedError("vendor timeout for AAPL")
    assert "vendor timeout for AAPL" in str(err)
