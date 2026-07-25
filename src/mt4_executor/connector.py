"""MetaApi account lifecycle: provision -> deploy -> connect -> synchronize."""

from __future__ import annotations

import logging
from typing import Any, Optional

from mt4_executor.config import Settings
from mt4_executor.errors import ConnectorError

logger = logging.getLogger(__name__)


class Mt4Connector:
    """Owns the MetaApi connection lifecycle for a single MT4 account.

    Usage::

        async with Mt4Connector(settings) as connection:
            executor = TradeExecutor(connection)
            ...

    The MetaApi SDK is imported lazily so the rest of the package (and its unit
    tests) does not require the SDK or any network access to import.
    """

    def __init__(self, settings: Settings, *, undeploy_on_close: bool = False) -> None:
        self._settings = settings
        self._undeploy_on_close = undeploy_on_close
        self._api: Any = None
        self._account: Any = None
        self._connection: Any = None

    async def connect(self) -> Any:
        """Provision (if needed), deploy, connect, and synchronize the account.

        Returns the live RPC connection object.
        """
        try:
            from metaapi_cloud_sdk import MetaApi
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ConnectorError(
                "metaapi-cloud-sdk is not installed; run `uv sync` or `pip install -e .`"
            ) from exc

        opts = {"region": self._settings.region} if self._settings.region else {}
        self._api = MetaApi(self._settings.token, opts)

        account = await self._find_existing_account()
        if account is None:
            logger.info("Provisioning new MT4 account %s on MetaApi", self._settings.login)
            account = await self._api.metatrader_account_api.create_account(
                {
                    "name": self._settings.account_name,
                    "type": "cloud",
                    "login": self._settings.login,
                    "password": self._settings.password,
                    "server": self._settings.server,
                    "platform": self._settings.platform,
                    "magic": self._settings.magic,
                }
            )
        else:
            logger.info("Reusing existing MetaApi account for login %s", self._settings.login)

        self._account = account

        logger.info("Deploying account and waiting for broker connection")
        await account.deploy()
        await account.wait_connected()

        connection = account.get_rpc_connection()
        await connection.connect()
        logger.info("Synchronizing terminal state (may take a moment)")
        await connection.wait_synchronized()

        self._connection = connection
        return connection

    @property
    def account(self) -> Any:
        """The underlying MetaApi account handle (available after connect())."""
        return self._account

    @property
    def connection(self) -> Any:
        """The live RPC connection (available after connect())."""
        return self._connection

    async def _find_existing_account(self) -> Optional[Any]:
        accounts = await self._api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()
        for item in accounts:
            if str(item.login) == str(self._settings.login) and item.type.startswith("cloud"):
                return item
        return None

    async def close(self, *, undeploy: bool = False) -> None:
        """Close the connection. Optionally undeploy the account to free resources.

        Undeploying stops MetaApi billing the deployed-account resource but means
        the next connect() must re-deploy and re-sync (slower). For an
        always-on autonomous connector, keep the account deployed.
        """
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        if undeploy and self._account is not None:
            logger.info("Undeploying MetaApi account")
            await self._account.undeploy()

    async def __aenter__(self) -> Any:
        return await self.connect()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close(undeploy=self._undeploy_on_close)
