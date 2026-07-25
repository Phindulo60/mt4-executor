import pytest

from mt4_executor.controlplane import CommandStatus, CommandType, SupabaseControlPlane
from mt4_executor.errors import ControlPlaneError


class FakeResponse:
    def __init__(self, json_data=None, raise_exc=None):
        self._json = json_data or []
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise:
            raise self._raise

    def json(self):
        return self._json


class FakeHttpClient:
    """Records calls and returns queued responses."""

    def __init__(self):
        self.calls = []
        self.get_response = FakeResponse([])
        self.mutate_response = FakeResponse([])

    async def get(self, url, params=None):
        self.calls.append(("get", url, params))
        return self.get_response

    async def patch(self, url, params=None, json=None):
        self.calls.append(("patch", url, params, json))
        return self.mutate_response

    async def post(self, url, params=None, headers=None, json=None):
        self.calls.append(("post", url, json))
        return self.mutate_response

    async def aclose(self):
        pass


def _cp_with_client(client):
    cp = SupabaseControlPlane("https://x.supabase.co", "svc-key", bot_id="bot1")
    cp._client = client  # inject fake, bypass real httpx
    return cp


def test_requires_url_and_key():
    with pytest.raises(ControlPlaneError):
        SupabaseControlPlane("", "key")
    with pytest.raises(ControlPlaneError):
        SupabaseControlPlane("https://x", "")


async def test_fetch_pending_commands_parses_and_filters():
    client = FakeHttpClient()
    client.get_response = FakeResponse([
        {"id": 1, "type": "start", "payload": {}},
        {"id": 2, "type": "buy", "payload": {"symbol": "EURUSD", "volume": 0.1}},
    ])
    cp = _cp_with_client(client)
    commands = await cp.fetch_pending_commands()
    assert [c.type for c in commands] == [CommandType.START, CommandType.BUY]
    _, url, params = client.calls[0]
    assert url.endswith("/commands")
    assert params["bot_id"] == "eq.bot1"
    assert params["status"] == "eq.pending"


async def test_publish_state_upserts_with_bot_id():
    client = FakeHttpClient()
    cp = _cp_with_client(client)
    await cp.publish_state({"running": True, "equity": 100})
    method, url, body = client.calls[0]
    assert method == "post"
    assert url.endswith("/bot_state")
    assert body["bot_id"] == "bot1"
    assert body["running"] is True
    assert "updated_at" in body


async def test_ack_command_patches_status():
    client = FakeHttpClient()
    cp = _cp_with_client(client)
    await cp.ack_command("42", CommandStatus.DONE, "ok")
    method, url, params, body = client.calls[0]
    assert method == "patch"
    assert params["id"] == "eq.42"
    assert body["status"] == "done"
    assert body["detail"] == "ok"


async def test_record_trade_posts_to_trades():
    client = FakeHttpClient()
    cp = _cp_with_client(client)
    await cp.record_trade({"source": "manual", "string_code": "TRADE_RETCODE_DONE"})
    method, url, body = client.calls[0]
    assert url.endswith("/trades")
    assert body["bot_id"] == "bot1"
    assert body["source"] == "manual"


async def test_http_error_is_wrapped():
    client = FakeHttpClient()
    client.get_response = FakeResponse(raise_exc=RuntimeError("401 unauthorized"))
    cp = _cp_with_client(client)
    with pytest.raises(ControlPlaneError) as exc:
        await cp.fetch_pending_commands()
    assert "failed to fetch commands" in str(exc.value)
