import pytest

from mt4_executor.errors import TradeError, VolumeError
from mt4_executor.executor import TradeExecutor, normalize_volume
from mt4_executor.models import Side, TradeSignal


# --- normalize_volume (pure) ---------------------------------------------

SPEC = {"minVolume": 0.01, "maxVolume": 100.0, "volumeStep": 0.01}


def test_normalize_snaps_down_to_step():
    assert normalize_volume(0.117, SPEC) == 0.11


def test_normalize_no_float_drift():
    # 0.1 / 0.01 must snap cleanly to 0.1, not 0.09 from binary drift
    assert normalize_volume(0.1, SPEC) == 0.1


def test_normalize_clamps_to_max():
    assert normalize_volume(250.0, SPEC) == 100.0


def test_normalize_below_min_raises():
    with pytest.raises(VolumeError):
        normalize_volume(0.005, SPEC)


def test_normalize_bad_step_raises():
    with pytest.raises(VolumeError):
        normalize_volume(0.1, {"volumeStep": 0})


def test_normalize_nonpositive_raises():
    with pytest.raises(VolumeError):
        normalize_volume(0, SPEC)


# --- TradeExecutor (mocked connection) -----------------------------------

class FakeConnection:
    def __init__(self, spec=None, positions=None, raise_on_trade=None):
        self._spec = spec or SPEC
        self._positions = positions or []
        self._raise = raise_on_trade
        self.calls = []

    async def get_symbol_specification(self, symbol):
        return self._spec

    async def get_positions(self):
        return self._positions

    async def get_account_information(self):
        return {"balance": 10000, "currency": "USD"}

    async def _trade_ok(self, action, *args):
        self.calls.append((action, args))
        if self._raise:
            raise self._raise
        return {"stringCode": "TRADE_RETCODE_DONE", "numericCode": 10009,
                "orderId": "1", "positionId": "9"}

    async def create_market_buy_order(self, *args):
        return await self._trade_ok("buy", *args)

    async def create_market_sell_order(self, *args):
        return await self._trade_ok("sell", *args)

    async def close_position(self, position_id, options=None):
        self.calls.append(("close", position_id))
        return {"stringCode": "TRADE_RETCODE_DONE", "positionId": position_id}

    async def modify_position(self, position_id, sl=None, tp=None):
        self.calls.append(("modify", position_id, sl, tp))
        return {"stringCode": "TRADE_RETCODE_DONE", "positionId": position_id}


async def test_execute_normalizes_volume_and_routes_buy():
    conn = FakeConnection()
    ex = TradeExecutor(conn)
    sig = TradeSignal(symbol="EURUSD", side=Side.BUY, volume=0.117,
                      stop_loss=1.05, take_profit=1.15, comment="e", client_id="c")
    result = await ex.execute(sig)
    assert result.succeeded
    action, args = conn.calls[0]
    assert action == "buy"
    # args = (symbol, volume, sl, tp, options)
    assert args[0] == "EURUSD"
    assert args[1] == 0.11  # normalized down from 0.117
    assert args[2] == 1.05
    assert args[4] == {"comment": "e", "clientId": "c"}


async def test_execute_routes_sell():
    conn = FakeConnection()
    ex = TradeExecutor(conn)
    await ex.market_sell("GBPUSD", 0.05)
    assert conn.calls[0][0] == "sell"


async def test_execute_no_normalize_passes_raw_volume():
    conn = FakeConnection()
    ex = TradeExecutor(conn)
    sig = TradeSignal(symbol="EURUSD", side=Side.BUY, volume=0.117)
    await ex.execute(sig, normalize=False)
    assert conn.calls[0][1][1] == 0.117


async def test_trade_error_is_wrapped():
    boom = Exception("rejected")
    boom.stringCode = "TRADE_RETCODE_NO_MONEY"
    boom.numericCode = 10019
    conn = FakeConnection(raise_on_trade=boom)
    ex = TradeExecutor(conn)
    with pytest.raises(TradeError) as exc:
        await ex.market_buy("EURUSD", 0.1)
    assert exc.value.string_code == "TRADE_RETCODE_NO_MONEY"
    assert exc.value.numeric_code == 10019


async def test_close_all_filters_by_symbol():
    positions = [
        {"id": "1", "symbol": "EURUSD"},
        {"id": "2", "symbol": "GBPUSD"},
        {"id": "3", "symbol": "EURUSD"},
    ]
    conn = FakeConnection(positions=positions)
    ex = TradeExecutor(conn)
    results = await ex.close_all(symbol="EURUSD")
    closed_ids = [c[1] for c in conn.calls if c[0] == "close"]
    assert closed_ids == ["1", "3"]
    assert len(results) == 2
