"""Market data access on top of a connected MetaApi RPC connection."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from mt4_executor.errors import MarketDataError
from mt4_executor.models import Candle, Price

# Timeframes MetaApi supports for MT4 accounts.
MT4_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mn"}


class MarketData:
    """Reads prices and candles.

    Latest price/candle come from the live RPC connection; historical candles
    come from the account handle (MetaApi's historical market data API). The
    account is optional so real-time-only use does not require it.
    """

    def __init__(self, connection: Any, account: Any = None) -> None:
        self._conn = connection
        self._account = account

    async def get_price(self, symbol: str) -> Price:
        try:
            raw = await self._conn.get_symbol_price(symbol)
        except Exception as exc:  # noqa: BLE001
            raise MarketDataError(f"failed to get price for {symbol}: {exc}") from exc
        return Price.from_response(raw)

    async def get_latest_candle(self, symbol: str, timeframe: str) -> Candle:
        self._check_timeframe(timeframe)
        try:
            raw = await self._conn.get_candle(symbol, timeframe)
        except Exception as exc:  # noqa: BLE001
            raise MarketDataError(
                f"failed to get {timeframe} candle for {symbol}: {exc}"
            ) from exc
        return Candle.from_response(raw)

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        start_time: Optional[datetime] = None,
    ) -> List[Candle]:
        """Return up to ``limit`` historical candles, sorted oldest-first.

        So ``candles[-1]`` is always the most recent candle, regardless of the
        order MetaApi returns them in.
        """
        self._check_timeframe(timeframe)
        if self._account is None:
            raise MarketDataError(
                "historical candles require an account handle "
                "(MarketData was created without one)"
            )
        if limit > 1000:
            raise MarketDataError("MetaApi limits historical candles to 1000 per request")
        try:
            raw = await self._account.get_historical_candles(
                symbol, timeframe, start_time, limit
            )
        except Exception as exc:  # noqa: BLE001
            raise MarketDataError(
                f"failed to get historical candles for {symbol}: {exc}"
            ) from exc
        candles = [Candle.from_response(c) for c in raw]
        candles.sort(key=lambda c: c.time)
        return candles

    @staticmethod
    def _check_timeframe(timeframe: str) -> None:
        if timeframe not in MT4_TIMEFRAMES:
            raise MarketDataError(
                f"unsupported MT4 timeframe {timeframe!r}; "
                f"allowed: {sorted(MT4_TIMEFRAMES)}"
            )
