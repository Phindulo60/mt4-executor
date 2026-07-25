"""Standalone autonomous MT4 trade-execution connector built on MetaApi.cloud."""

from mt4_executor.config import Settings
from mt4_executor.connector import Mt4Connector
from mt4_executor.controlplane import (
    Command,
    CommandStatus,
    CommandType,
    ControlPlane,
    InMemoryControlPlane,
    SupabaseControlPlane,
)
from mt4_executor.engine import Engine
from mt4_executor.errors import (
    ConfigError,
    ConnectorError,
    ControlPlaneError,
    MarketDataError,
    Mt4ExecutorError,
    TradeError,
    VolumeError,
)
from mt4_executor.executor import TradeExecutor, normalize_volume
from mt4_executor.marketdata import MarketData
from mt4_executor.models import Candle, Price, Side, TradeResult, TradeSignal
from mt4_executor.runner import LoopConfig, TradingLoop
from mt4_executor.strategy import HoldStrategy, MarketSnapshot, Strategy

__all__ = [
    "Settings",
    "Mt4Connector",
    "TradeExecutor",
    "normalize_volume",
    "MarketData",
    "TradingLoop",
    "LoopConfig",
    "Strategy",
    "HoldStrategy",
    "MarketSnapshot",
    "Engine",
    "ControlPlane",
    "InMemoryControlPlane",
    "SupabaseControlPlane",
    "Command",
    "CommandType",
    "CommandStatus",
    "Side",
    "TradeSignal",
    "TradeResult",
    "Candle",
    "Price",
    "Mt4ExecutorError",
    "ConfigError",
    "ConnectorError",
    "TradeError",
    "VolumeError",
    "MarketDataError",
    "ControlPlaneError",
]

__version__ = "0.1.0"
