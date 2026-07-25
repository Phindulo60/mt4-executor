"""The autonomous trading loop: market data -> strategy -> execution."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List

from mt4_executor.executor import TradeExecutor
from mt4_executor.marketdata import MarketData
from mt4_executor.models import TradeResult
from mt4_executor.strategy import MarketSnapshot, Strategy

logger = logging.getLogger(__name__)


@dataclass
class LoopConfig:
    """Runtime configuration for the trading loop."""

    symbols: List[str]
    timeframe: str = "1h"
    poll_interval: float = 60.0
    history_size: int = 100

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("LoopConfig requires at least one symbol")
        if self.poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if self.history_size < 1:
            raise ValueError("history_size must be >= 1")


class TradingLoop:
    """Polls market data, asks the strategy for a decision, and executes it.

    The loop owns no trading logic and no risk logic; it only wires the three
    layers together and keeps running. One symbol (or one iteration) raising an
    exception is logged and isolated so the loop stays alive.
    """

    def __init__(
        self,
        market_data: MarketData,
        executor: TradeExecutor,
        strategy: Strategy,
        config: LoopConfig,
    ) -> None:
        self._data = market_data
        self._executor = executor
        self._strategy = strategy
        self._config = config
        self._stop = asyncio.Event()

    def stop(self) -> None:
        """Signal the loop to finish the current wait and exit run_forever()."""
        logger.info("stop requested")
        self._stop.set()

    async def _snapshot(self, symbol: str) -> MarketSnapshot:
        candles = await self._data.get_candles(
            symbol, self._config.timeframe, self._config.history_size
        )
        price = await self._data.get_price(symbol)
        return MarketSnapshot(
            symbol=symbol,
            timeframe=self._config.timeframe,
            candles=candles,
            price=price,
        )

    async def run_once(self) -> List[TradeResult]:
        """Run a single pass over all configured symbols."""
        results: List[TradeResult] = []
        for symbol in self._config.symbols:
            try:
                snapshot = await self._snapshot(symbol)
                signal = await self._strategy.decide(snapshot)
                if signal is None:
                    logger.debug("%s: strategy returned no signal", symbol)
                    continue
                logger.info("%s: strategy signalled %s %s", symbol, signal.side.value, signal.volume)
                result = await self._executor.execute(signal)
                logger.info("%s: execution result %s", symbol, result.string_code)
                results.append(result)
            except Exception:  # noqa: BLE001 - isolate per-symbol failures
                logger.exception("iteration failed for symbol %s", symbol)
        return results

    async def run_forever(self) -> None:
        """Run run_once() every ``poll_interval`` seconds until stop() is called."""
        cfg = self._config
        logger.info(
            "starting loop: symbols=%s timeframe=%s interval=%ss history=%s",
            cfg.symbols, cfg.timeframe, cfg.poll_interval, cfg.history_size,
        )
        while not self._stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=cfg.poll_interval)
            except asyncio.TimeoutError:
                pass  # interval elapsed; run again
        logger.info("loop stopped")
