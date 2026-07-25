"""Strategy seam: the pluggable decision layer of the autonomous loop.

This module intentionally contains no trading logic yet. It defines the
interface (:class:`Strategy`) that the loop calls and a no-op placeholder
(:class:`HoldStrategy`). Drop in a real strategy later by implementing
``decide`` — nothing else in the loop needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, runtime_checkable

from mt4_executor.models import Candle, Price, TradeSignal


@dataclass
class MarketSnapshot:
    """Everything the loop hands a strategy for one symbol on one iteration."""

    symbol: str
    timeframe: str
    candles: List[Candle] = field(default_factory=list)
    price: Optional[Price] = None

    @property
    def latest(self) -> Optional[Candle]:
        """Most recent candle (candles are sorted oldest-first)."""
        return self.candles[-1] if self.candles else None


@runtime_checkable
class Strategy(Protocol):
    """Turns a market snapshot into an optional trade signal.

    Return ``None`` to do nothing this iteration, or a :class:`TradeSignal`
    to open a position.
    """

    async def decide(self, snapshot: MarketSnapshot) -> Optional[TradeSignal]:
        ...


class HoldStrategy:
    """Placeholder strategy that never trades.

    Lets you run the full data->execute loop end-to-end (it will fetch market
    data every iteration and simply decide to do nothing). Replace with real
    logic when ready.
    """

    async def decide(self, snapshot: MarketSnapshot) -> Optional[TradeSignal]:
        return None
