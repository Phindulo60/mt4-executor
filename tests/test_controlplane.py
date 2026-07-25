import pytest

from mt4_executor.controlplane import (
    Command,
    CommandStatus,
    CommandType,
    InMemoryControlPlane,
)
from mt4_executor.errors import ControlPlaneError


def test_command_type_parse():
    assert CommandType.parse("BUY") is CommandType.BUY
    assert CommandType.parse(" flatten ") is CommandType.FLATTEN
    with pytest.raises(ControlPlaneError):
        CommandType.parse("nuke")


def test_command_from_row():
    cmd = Command.from_row(
        {"id": 7, "type": "buy", "payload": {"symbol": "EURUSD", "volume": 0.1},
         "created_at": "2026-01-01T00:00:00Z"}
    )
    assert cmd.id == "7"
    assert cmd.type is CommandType.BUY
    assert cmd.payload["symbol"] == "EURUSD"


async def test_in_memory_queue_roundtrip():
    cp = InMemoryControlPlane()
    cp.enqueue(CommandType.START)
    cp.enqueue(CommandType.BUY, {"symbol": "EURUSD", "volume": 0.1})

    first = await cp.fetch_pending_commands()
    assert [c.type for c in first] == [CommandType.START, CommandType.BUY]
    # queue drained
    assert await cp.fetch_pending_commands() == []

    await cp.ack_command("1", CommandStatus.DONE, "ok")
    assert cp.acked[0]["status"] == "done"


async def test_in_memory_publish_and_record():
    cp = InMemoryControlPlane()
    await cp.publish_state({"running": True, "equity": 100})
    await cp.record_trade({"source": "manual", "string_code": "TRADE_RETCODE_DONE"})
    assert cp.states[-1]["equity"] == 100
    assert cp.trades[-1]["source"] == "manual"
