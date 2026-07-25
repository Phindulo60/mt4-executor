import pytest

from mt4_executor.errors import MarketDataError
from mt4_executor.marketdata import MarketData


class FakeConn:
    async def get_symbol_price(self, symbol):
        return {"symbol": symbol, "bid": 1.1000, "ask": 1.1002, "time": "t"}

    async def get_candle(self, symbol, timeframe):
        return {"symbol": symbol, "timeframe": timeframe, "time": "t",
                "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1}


class FakeAccount:
    def __init__(self, candles):
        self._candles = candles

    async def get_historical_candles(self, symbol, timeframe, start_time, limit):
        return self._candles


def _candle(t, close):
    return {"symbol": "EURUSD", "timeframe": "1h", "time": t,
            "open": close, "high": close, "low": close, "close": close}


async def test_get_price_parses():
    md = MarketData(FakeConn())
    price = await md.get_price("EURUSD")
    assert price.bid == 1.1000
    assert price.ask == 1.1002
    assert price.mid == pytest.approx(1.1001)


async def test_get_latest_candle_parses():
    md = MarketData(FakeConn())
    c = await md.get_latest_candle("EURUSD", "1h")
    assert c.close == 1.1
    assert c.high == 1.2


async def test_get_candles_sorted_oldest_first():
    # deliberately supplied newest-first to prove we re-sort
    raw = [_candle(3, 1.3), _candle(1, 1.1), _candle(2, 1.2)]
    md = MarketData(FakeConn(), account=FakeAccount(raw))
    candles = await md.get_candles("EURUSD", "1h", limit=3)
    assert [c.time for c in candles] == [1, 2, 3]
    assert candles[-1].close == 1.3


async def test_get_candles_requires_account():
    md = MarketData(FakeConn())
    with pytest.raises(MarketDataError):
        await md.get_candles("EURUSD", "1h")


async def test_invalid_timeframe_rejected():
    md = MarketData(FakeConn())
    with pytest.raises(MarketDataError):
        await md.get_latest_candle("EURUSD", "7m")


async def test_limit_over_1000_rejected():
    md = MarketData(FakeConn(), account=FakeAccount([]))
    with pytest.raises(MarketDataError):
        await md.get_candles("EURUSD", "1h", limit=1001)
