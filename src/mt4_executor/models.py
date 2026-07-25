"""Trade domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class Side(str, Enum):
    """Direction of a market order."""

    BUY = "buy"
    SELL = "sell"

    @classmethod
    def parse(cls, value: str) -> "Side":
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            raise ValueError(f"Invalid side {value!r}; expected 'buy' or 'sell'") from exc


@dataclass
class TradeSignal:
    """A request to open a market position."""

    symbol: str
    side: Side
    volume: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    comment: Optional[str] = None
    client_id: Optional[str] = None

    def options(self) -> Dict[str, Any]:
        """Build the MetaApi trade ``options`` dict from the optional fields."""
        opts: Dict[str, Any] = {}
        if self.comment is not None:
            opts["comment"] = self.comment
        if self.client_id is not None:
            opts["clientId"] = self.client_id
        return opts


@dataclass
class TradeResult:
    """Normalized result of a trade request."""

    string_code: str
    numeric_code: Optional[int] = None
    order_id: Optional[str] = None
    position_id: Optional[str] = None
    message: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.string_code == "TRADE_RETCODE_DONE"

    @classmethod
    def from_response(cls, response: Dict[str, Any]) -> "TradeResult":
        return cls(
            string_code=response.get("stringCode", "UNKNOWN"),
            numeric_code=response.get("numericCode"),
            order_id=response.get("orderId"),
            position_id=response.get("positionId"),
            message=response.get("message"),
            raw=dict(response),
        )


@dataclass
class Price:
    """Latest bid/ask for a symbol."""

    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    time: Any = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def mid(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2

    @classmethod
    def from_response(cls, response: Dict[str, Any]) -> "Price":
        return cls(
            symbol=response.get("symbol", ""),
            bid=response.get("bid"),
            ask=response.get("ask"),
            time=response.get("time"),
            raw=dict(response),
        )


@dataclass
class Candle:
    """A single OHLC candle."""

    symbol: str
    timeframe: str
    time: Any
    open: float
    high: float
    low: float
    close: float
    tick_volume: Optional[float] = None
    volume: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, response: Dict[str, Any]) -> "Candle":
        return cls(
            symbol=response.get("symbol", ""),
            timeframe=response.get("timeframe", ""),
            time=response.get("time"),
            open=response["open"],
            high=response["high"],
            low=response["low"],
            close=response["close"],
            tick_volume=response.get("tickVolume"),
            volume=response.get("volume"),
            raw=dict(response),
        )
