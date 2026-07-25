import asyncio

import pytest

from mt4_executor.models import Side, TradeResult, TradeSignal
from mt4_executor.runner import LoopConfig, TradingLoop
from mt4_executor.strategy import HoldStrategy, MarketSnapshot


class FakeMarketData:
    def __init__(self, fail_symbols=None):
        self.fail_symbols = fail_symbols or set()
        self.snapshots = []

    async def get_candles(self, symbol, timeframe, limit):
        if symbol in self.fail_symbols:
            raise RuntimeError("data boom")
        return []

    async def get_price(self, symbol):
        return None


class FakeExecutor:
    def __init__(self):
        self.executed = []

    async def execute(self, signal):
        self.executed.append(signal)
        return TradeResult(string_code="TRADE_RETCODE_DONE", position_id="1")


class SignalStrategy:
    """Emits a buy for a specific symbol, holds otherwise."""

    def __init__(self, symbol):
        self.symbol = symbol

    async def decide(self, snapshot: MarketSnapshot):
        if snapshot.symbol == self.symbol:
            return TradeSignal(symbol=snapshot.symbol, side=Side.BUY, volume=0.1)
        return None


def _loop(market, executor, strategy, **cfg):
    config = LoopConfig(symbols=cfg.pop("symbols", ["EURUSD"]), **cfg)
    return TradingLoop(market, executor, strategy, config)


def test_loop_config_validates():
    with pytest.raises(ValueError):
        LoopConfig(symbols=[])
    with pytest.raises(ValueError):
        LoopConfig(symbols=["EURUSD"], poll_interval=0)
    with pytest.raises(ValueError):
        LoopConfig(symbols=["EURUSD"], history_size=0)


async def test_run_once_holds_with_placeholder():
    executor = FakeExecutor()
    loop = _loop(FakeMarketData(), executor, HoldStrategy(), symbols=["EURUSD", "GBPUSD"])
    results = await loop.run_once()
    assert results == []
    assert executor.executed == []


async def test_run_once_executes_on_signal():
    executor = FakeExecutor()
    loop = _loop(FakeMarketData(), executor, SignalStrategy("EURUSD"),
                 symbols=["EURUSD", "GBPUSD"])
    results = await loop.run_once()
    assert len(results) == 1
    assert [s.symbol for s in executor.executed] == ["EURUSD"]


async def test_run_once_isolates_failing_symbol():
    executor = FakeExecutor()
    market = FakeMarketData(fail_symbols={"EURUSD"})
    loop = _loop(market, executor, SignalStrategy("GBPUSD"),
                 symbols=["EURUSD", "GBPUSD"])
    # EURUSD data fails but must not stop GBPUSD from trading
    results = await loop.run_once()
    assert len(results) == 1
    assert executor.executed[0].symbol == "GBPUSD"


async def test_run_forever_stops_cleanly():
    executor = FakeExecutor()
    loop = _loop(FakeMarketData(), executor, HoldStrategy(),
                 symbols=["EURUSD"], poll_interval=0.01)
    task = asyncio.create_task(loop.run_forever())
    await asyncio.sleep(0.05)
    loop.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done()
