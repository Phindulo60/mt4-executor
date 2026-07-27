import pytest

from mt4_executor.controlplane import CommandStatus, CommandType, InMemoryControlPlane
from mt4_executor.engine import Engine
from mt4_executor.models import Side, TradeResult, TradeSignal
from mt4_executor.runner import LoopConfig, TradingLoop
from mt4_executor.strategy import HoldStrategy, MarketSnapshot


class FakeMarketData:
    async def get_candles(self, symbol, timeframe, limit):
        return []

    async def get_price(self, symbol):
        return None


class FakeExecutor:
    def __init__(self, positions=None):
        self.executed = []
        self.closed_all = 0
        self._positions = positions or []

    async def execute(self, signal):
        self.executed.append(signal)
        return TradeResult(string_code="TRADE_RETCODE_DONE", position_id="p1")

    async def close_all(self, symbol=None):
        self.closed_all += 1
        results = [TradeResult(string_code="TRADE_RETCODE_DONE", position_id=str(i))
                   for i, _ in enumerate(self._positions)]
        self._positions = []
        return results

    async def get_account_information(self):
        return {"balance": 1000, "equity": 1010, "currency": "USD"}

    async def get_positions(self):
        return self._positions


class SignalStrategy:
    async def decide(self, snapshot: MarketSnapshot):
        return TradeSignal(symbol=snapshot.symbol, side=Side.BUY, volume=0.1)


def _engine(executor, cp, strategy=None, start_running=False, server=None):
    loop = TradingLoop(FakeMarketData(), executor, strategy or HoldStrategy(),
                       LoopConfig(symbols=["EURUSD"], poll_interval=1))
    return Engine(loop, executor, cp, poll_interval=1,
                  start_running=start_running, server=server)


async def test_start_and_stop_commands_toggle_running():
    cp = InMemoryControlPlane()
    executor = FakeExecutor()
    engine = _engine(executor, cp)
    assert engine.running is False

    cp.enqueue(CommandType.START)
    await engine.tick()
    assert engine.running is True

    cp.enqueue(CommandType.STOP)
    await engine.tick()
    assert engine.running is False
    # both commands acked done
    assert all(a["status"] == "done" for a in cp.acked)


async def test_paused_engine_does_not_trade_but_publishes_state():
    cp = InMemoryControlPlane()
    executor = FakeExecutor()
    engine = _engine(executor, cp, strategy=SignalStrategy(), start_running=False)
    await engine.tick()
    assert executor.executed == []          # paused -> strategy not run
    assert cp.states[-1]["running"] is False
    assert cp.states[-1]["equity"] == 1010  # telemetry still published


async def test_running_engine_executes_strategy_and_records_trade():
    cp = InMemoryControlPlane()
    executor = FakeExecutor()
    engine = _engine(executor, cp, strategy=SignalStrategy(), start_running=True)
    await engine.tick()
    assert len(executor.executed) == 1
    assert any(t["source"] == "strategy" for t in cp.trades)


async def test_flatten_command_closes_all():
    cp = InMemoryControlPlane()
    executor = FakeExecutor(positions=[{"id": "1"}, {"id": "2"}])
    engine = _engine(executor, cp)
    cp.enqueue(CommandType.FLATTEN)
    await engine.tick()
    assert executor.closed_all == 1
    assert cp.acked[-1]["status"] == "done"


async def test_manual_buy_command_executes():
    cp = InMemoryControlPlane()
    executor = FakeExecutor()
    engine = _engine(executor, cp)
    cp.enqueue(CommandType.BUY, {"symbol": "GBPUSD", "volume": 0.05, "sl": 1.2})
    await engine.tick()
    assert executor.executed[0].symbol == "GBPUSD"
    assert executor.executed[0].side is Side.BUY
    assert any(t["source"] == "manual" for t in cp.trades)


async def test_manual_trade_missing_fields_fails_gracefully():
    cp = InMemoryControlPlane()
    executor = FakeExecutor()
    engine = _engine(executor, cp)
    cp.enqueue(CommandType.SELL, {"symbol": "EURUSD"})  # no volume
    await engine.tick()
    assert executor.executed == []
    assert cp.acked[-1]["status"] == "failed"
    assert "volume" in (cp.acked[-1]["detail"] or "")


async def test_bad_command_fetch_does_not_crash_tick():
    class BrokenCP(InMemoryControlPlane):
        async def fetch_pending_commands(self):
            raise RuntimeError("db down")

    cp = BrokenCP()
    executor = FakeExecutor()
    engine = _engine(executor, cp)
    await engine.tick()  # must not raise
    assert cp.states[-1]["last_error"] is not None


async def test_publishes_server_and_derived_mode():
    cp = InMemoryControlPlane()
    executor = FakeExecutor()
    engine = _engine(executor, cp, server="TradeNation-DemoBravo")
    await engine.tick()
    assert cp.states[-1]["server"] == "TradeNation-DemoBravo"
    assert cp.states[-1]["mode"] == "demo"


async def test_derive_mode_classifies_live_and_none():
    from mt4_executor.engine import _derive_mode
    assert _derive_mode("TradeNation-LiveBravo") == "live"
    assert _derive_mode("Broker-Demo") == "demo"
    assert _derive_mode(None) is None


async def test_telemetry_failure_increments_stale_and_still_publishes():
    class FailingTelemetry(FakeExecutor):
        async def get_account_information(self):
            raise RuntimeError("MetaApi websocket timed out")

    cp = InMemoryControlPlane()
    engine = _engine(FailingTelemetry(), cp)
    await engine.tick()
    # heartbeat still published (dashboard stays live), with the error surfaced
    assert cp.states[-1]["last_error"].startswith("telemetry:")
    assert engine._stale_ticks == 1


async def test_engine_exits_when_telemetry_stale_too_long():
    import pytest as _pytest
    from mt4_executor.errors import EngineWedgedError

    class FailingTelemetry(FakeExecutor):
        async def get_account_information(self):
            raise RuntimeError("wedged")

    cp = InMemoryControlPlane()
    loop = TradingLoop(FakeMarketData(), FailingTelemetry(), HoldStrategy(),
                       LoopConfig(symbols=["EURUSD"], poll_interval=1))
    engine = Engine(loop, FailingTelemetry(), cp, poll_interval=0.001,
                    max_stale_ticks=3)
    with _pytest.raises(EngineWedgedError):
        await engine.run_forever()
    assert engine._stale_ticks >= 3


async def test_stale_ticks_reset_after_recovery():
    class Flaky(FakeExecutor):
        def __init__(self):
            super().__init__()
            self.fail = True

        async def get_account_information(self):
            if self.fail:
                raise RuntimeError("transient")
            return {"balance": 1000, "equity": 1000, "currency": "USD"}

    cp = InMemoryControlPlane()
    ex = Flaky()
    engine = _engine(ex, cp)
    await engine.tick()
    assert engine._stale_ticks == 1
    ex.fail = False
    await engine.tick()
    assert engine._stale_ticks == 0


async def test_hanging_telemetry_times_out():
    import asyncio as _asyncio

    class Hanging(FakeExecutor):
        async def get_account_information(self):
            await _asyncio.sleep(5)
            return {}

    cp = InMemoryControlPlane()
    loop = TradingLoop(FakeMarketData(), Hanging(), HoldStrategy(),
                       LoopConfig(symbols=["EURUSD"], poll_interval=1))
    engine = Engine(loop, Hanging(), cp, poll_interval=1, telemetry_timeout=0.01)
    await engine.tick()  # must return quickly, not hang
    assert engine._stale_ticks == 1
    assert "telemetry:" in cp.states[-1]["last_error"]
