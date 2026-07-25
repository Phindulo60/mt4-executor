import pytest

from mt4_executor.models import Side, TradeResult, TradeSignal


def test_side_parse():
    assert Side.parse("BUY") is Side.BUY
    assert Side.parse(" sell ") is Side.SELL
    with pytest.raises(ValueError):
        Side.parse("hold")


def test_signal_options_omits_none():
    sig = TradeSignal(symbol="EURUSD", side=Side.BUY, volume=0.1)
    assert sig.options() == {}


def test_signal_options_includes_set_fields():
    sig = TradeSignal(
        symbol="EURUSD", side=Side.BUY, volume=0.1,
        comment="entry", client_id="abc",
    )
    assert sig.options() == {"comment": "entry", "clientId": "abc"}


def test_trade_result_from_response_success():
    result = TradeResult.from_response(
        {"stringCode": "TRADE_RETCODE_DONE", "numericCode": 10009,
         "orderId": "111", "positionId": "222"}
    )
    assert result.succeeded is True
    assert result.order_id == "111"
    assert result.position_id == "222"


def test_trade_result_from_response_failure():
    result = TradeResult.from_response({"stringCode": "TRADE_RETCODE_REJECT"})
    assert result.succeeded is False
    assert result.numeric_code is None


def test_price_mid_and_parse():
    from mt4_executor.models import Price
    p = Price.from_response({"symbol": "EURUSD", "bid": 1.10, "ask": 1.12})
    assert p.mid == pytest.approx(1.11)
    empty = Price.from_response({"symbol": "X"})
    assert empty.mid is None


def test_candle_parse():
    from mt4_executor.models import Candle
    c = Candle.from_response({
        "symbol": "EURUSD", "timeframe": "1h", "time": "t",
        "open": 1.0, "high": 1.3, "low": 0.9, "close": 1.2, "tickVolume": 42,
    })
    assert c.close == 1.2
    assert c.tick_volume == 42
