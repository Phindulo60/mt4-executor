"""Tests for Mt4Connector lifecycle plumbing (no network / no SDK required)."""

import pytest

from mt4_executor.config import Settings
from mt4_executor.connector import Mt4Connector


class FakeAccount:
    def __init__(self):
        self.undeployed = False

    async def undeploy(self):
        self.undeployed = True


class FakeConnection:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


def _settings():
    return Settings(token="t", login="1", password="p", server="S")


async def test_close_without_undeploy_keeps_account_deployed():
    c = Mt4Connector(_settings())
    account, connection = FakeAccount(), FakeConnection()
    c._account, c._connection = account, connection
    await c.close()
    assert connection.closed is True
    assert account.undeployed is False


async def test_close_with_undeploy_frees_account():
    c = Mt4Connector(_settings())
    account, connection = FakeAccount(), FakeConnection()
    c._account, c._connection = account, connection
    await c.close(undeploy=True)
    assert account.undeployed is True


async def test_aexit_honors_undeploy_on_close_flag():
    c = Mt4Connector(_settings(), undeploy_on_close=True)
    account, connection = FakeAccount(), FakeConnection()
    c._account, c._connection = account, connection
    await c.__aexit__(None, None, None)
    assert account.undeployed is True


async def test_aexit_default_does_not_undeploy():
    c = Mt4Connector(_settings())
    account, connection = FakeAccount(), FakeConnection()
    c._account, c._connection = account, connection
    await c.__aexit__(None, None, None)
    assert account.undeployed is False
