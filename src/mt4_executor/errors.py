"""Domain exceptions for the MT4 executor."""

from __future__ import annotations

from typing import Optional


class Mt4ExecutorError(Exception):
    """Base class for all mt4-executor errors."""


class ConfigError(Mt4ExecutorError):
    """Raised when required configuration is missing or invalid."""


class ConnectorError(Mt4ExecutorError):
    """Raised when the MetaApi account lifecycle fails."""


class VolumeError(Mt4ExecutorError):
    """Raised when a requested volume cannot be normalized to broker limits."""


class MarketDataError(Mt4ExecutorError):
    """Raised when market data cannot be retrieved."""


class ControlPlaneError(Mt4ExecutorError):
    """Raised when the control plane (command/telemetry hub) fails."""


class EngineWedgedError(Mt4ExecutorError):
    """Raised when telemetry is unavailable for too long (wedged MetaApi link).

    The engine exits with this so the supervisor (ECS) restarts the task with a
    fresh MetaApi connection, rather than hanging silently with a stale heartbeat.
    """


class TradeError(Mt4ExecutorError):
    """Raised when a trade request is rejected by the broker or MetaApi.

    The MetaApi SDK raises ``TradeError`` with ``stringCode``/``numericCode``
    attributes; we surface both so callers can branch on the broker's reason.
    """

    def __init__(
        self,
        message: str,
        string_code: Optional[str] = None,
        numeric_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.string_code = string_code
        self.numeric_code = numeric_code
