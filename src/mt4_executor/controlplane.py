"""Control plane: the command + telemetry hub between the engine and the site.

The engine never exposes an inbound port. It *polls* a command queue and
*publishes* telemetry to a shared store (Supabase in production). This module
defines the seam (``ControlPlane``), the command model, an in-memory
implementation for tests/local runs, and a Supabase-backed implementation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from mt4_executor.errors import ControlPlaneError


class CommandType(str, Enum):
    """Commands the site can issue to the engine."""

    START = "start"      # resume running the strategy loop
    STOP = "stop"        # pause the strategy loop (engine stays alive)
    FLATTEN = "flatten"  # close all open positions
    BUY = "buy"          # manual market buy (payload: symbol, volume, sl?, tp?)
    SELL = "sell"        # manual market sell (payload: symbol, volume, sl?, tp?)

    @classmethod
    def parse(cls, value: str) -> "CommandType":
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ControlPlaneError(f"unknown command type {value!r}") from exc


class CommandStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Command:
    """A single instruction from the command center."""

    id: str
    type: CommandType
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Command":
        return cls(
            id=str(row["id"]),
            type=CommandType.parse(row["type"]),
            payload=row.get("payload") or {},
            created_at=row.get("created_at"),
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@runtime_checkable
class ControlPlane(Protocol):
    """Interface the engine uses to receive commands and publish telemetry."""

    async def fetch_pending_commands(self) -> List[Command]:
        ...

    async def ack_command(
        self, command_id: str, status: CommandStatus, detail: Optional[str] = None
    ) -> None:
        ...

    async def publish_state(self, state: Dict[str, Any]) -> None:
        ...

    async def record_trade(self, trade: Dict[str, Any]) -> None:
        ...


class InMemoryControlPlane:
    """In-memory control plane for tests and local dry runs."""

    def __init__(self) -> None:
        self.pending: List[Command] = []
        self.acked: List[Dict[str, Any]] = []
        self.states: List[Dict[str, Any]] = []
        self.trades: List[Dict[str, Any]] = []

    def enqueue(self, type: CommandType, payload: Optional[Dict[str, Any]] = None) -> Command:
        cmd = Command(
            id=str(len(self.acked) + len(self.pending) + 1),
            type=type,
            payload=payload or {},
            created_at=_utc_now_iso(),
        )
        self.pending.append(cmd)
        return cmd

    async def fetch_pending_commands(self) -> List[Command]:
        commands, self.pending = self.pending, []
        return commands

    async def ack_command(
        self, command_id: str, status: CommandStatus, detail: Optional[str] = None
    ) -> None:
        self.acked.append({"id": command_id, "status": status.value, "detail": detail})

    async def publish_state(self, state: Dict[str, Any]) -> None:
        self.states.append(state)

    async def record_trade(self, trade: Dict[str, Any]) -> None:
        self.trades.append(trade)


class SupabaseControlPlane:
    """Supabase-backed control plane using the PostgREST REST API over httpx.

    Outbound-only: the engine reaches Supabase, never the reverse. Uses the
    service-role key, so it must run server-side (the engine), never in a
    browser. Tables/policies are defined in schema.sql.
    """

    def __init__(self, url: str, service_key: str, bot_id: str = "default") -> None:
        if not url or not service_key:
            raise ControlPlaneError("Supabase url and service key are required")
        self._base = url.rstrip("/") + "/rest/v1"
        self._bot_id = bot_id
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        self._client: Any = None

    @classmethod
    def from_env(cls) -> "SupabaseControlPlane":
        return cls(
            url=os.getenv("SUPABASE_URL", ""),
            service_key=os.getenv("SUPABASE_SERVICE_KEY", ""),
            bot_id=os.getenv("BOT_ID", "default"),
        )

    async def _http(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover
                raise ControlPlaneError("httpx is required for SupabaseControlPlane") from exc
            self._client = httpx.AsyncClient(headers=self._headers, timeout=15.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_pending_commands(self) -> List[Command]:
        client = await self._http()
        try:
            resp = await client.get(
                f"{self._base}/commands",
                params={
                    "bot_id": f"eq.{self._bot_id}",
                    "status": "eq.pending",
                    "order": "created_at.asc",
                },
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise ControlPlaneError(f"failed to fetch commands: {exc}") from exc
        return [Command.from_row(row) for row in resp.json()]

    async def ack_command(
        self, command_id: str, status: CommandStatus, detail: Optional[str] = None
    ) -> None:
        client = await self._http()
        try:
            resp = await client.patch(
                f"{self._base}/commands",
                params={"id": f"eq.{command_id}"},
                json={"status": status.value, "detail": detail, "processed_at": _utc_now_iso()},
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise ControlPlaneError(f"failed to ack command {command_id}: {exc}") from exc

    async def publish_state(self, state: Dict[str, Any]) -> None:
        client = await self._http()
        body = {"bot_id": self._bot_id, "updated_at": _utc_now_iso(), **state}
        try:
            resp = await client.post(
                f"{self._base}/bot_state",
                params={"on_conflict": "bot_id"},
                headers={"Prefer": "resolution=merge-duplicates"},
                json=body,
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise ControlPlaneError(f"failed to publish state: {exc}") from exc

    async def record_trade(self, trade: Dict[str, Any]) -> None:
        client = await self._http()
        body = {"bot_id": self._bot_id, "created_at": _utc_now_iso(), **trade}
        try:
            resp = await client.post(f"{self._base}/trades", json=body)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise ControlPlaneError(f"failed to record trade: {exc}") from exc
