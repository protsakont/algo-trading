"""AlgoTradeError hierarchy (spec 01).

Adapters translate external exceptions into these at the boundary; entrypoints
translate them into exit codes and human-readable messages. Raw third-party
exceptions must never cross a module boundary.
"""


class AlgoTradeError(Exception):
    """Base class for every error raised by this system."""


class ConfigError(AlgoTradeError):
    """Invalid, missing, or unsafe configuration."""


class DataFeedError(AlgoTradeError):
    """Data vendor / storage failure surfaced by a DataFeed adapter."""


class BrokerError(AlgoTradeError):
    """Broker gateway failure (submit/cancel/positions)."""


class RiskRejected(AlgoTradeError):
    """An order proceeded despite a rejecting RiskVerdict.

    RiskChecker itself never raises to reject (it returns verdicts); this error
    exists for boundaries that must hard-stop when a veto is ignored.
    """
