"""The engine: wraps the trading loop with command handling + telemetry.

This is the always-on process. Each tick it:
  1. drains pending commands from the control plane (start/stop/flatten/manual),
  2. runs one strategy pass when active,
  3. publishes heartbeat + telemetry (status, balance/equity, positions).

The engine is host-agnostic - it is just an asyncio coroutine you run wherever
you host it (Oracle Free VM, Fly.io, Hetzner, ECS, ...).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from mt4_executor.controlplane import (
    Command,
    CommandStatus,
    CommandType,
    ControlPlane,
)
from mt4_executor.executor import TradeExecutor
from mt4_executor.models import Side, TradeSignal
from mt4_executor.runner import TradingLoop

logger = logging.getLogger(__name__)


class Engine:
    """Command-driven wrapper around a TradingLoop.

    ``start_running`` controls whether the strategy loop is active. Commands can
    flip it at runtime. Even when paused, the engine keeps publishing telemetry
    so the dashboard shows a live heartbeat.
    """

    def __init__(
        self,
        loop: TradingLoop,
        executor: TradeExecutor,
        control_plane: ControlPlane,
        *,
        poll_interval: float = 5.0,
        start_running: bool = False,
    ) -> None:
        self._loop = loop
        self._executor = executor
        self._cp = control_plane
        self._poll_interval = poll_interval
        self._running = start_running
        self._stop = asyncio.Event()
        self._last_error: Optional[str] = None

    @property
    def running(self) -> bool:
        return self._running

    def stop(self) -> None:
        logger.info("engine stop requested")
        self._stop.set()

    async def tick(self) -> None:
        """One engine iteration: commands -> strategy pass -> telemetry."""
        await self._drain_commands()
        if self._running:
            try:
                results = await self._loop.run_once()
                for result in results:
                    await self._cp.record_trade(
                        {"source": "strategy", "string_code": result.string_code,
                         "position_id": result.position_id, "raw": result.raw}
                    )
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                logger.exception("strategy pass failed")
        await self._publish_state()

    async def run_forever(self) -> None:
        logger.info("engine started (running=%s, poll=%ss)", self._running, self._poll_interval)
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - never let a tick kill the engine
                logger.exception("engine tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
            except asyncio.TimeoutError:
                pass
        logger.info("engine stopped")

    async def _drain_commands(self) -> None:
        try:
            commands = await self._cp.fetch_pending_commands()
        except Exception as exc:  # noqa: BLE001
            logger.exception("failed to fetch commands")
            self._last_error = str(exc)
            return
        for command in commands:
            await self._apply_command(command)

    async def _apply_command(self, command: Command) -> None:
        logger.info("applying command %s (%s)", command.type.value, command.id)
        try:
            detail = await self._dispatch(command)
            await self._cp.ack_command(command.id, CommandStatus.DONE, detail)
        except Exception as exc:  # noqa: BLE001
            logger.exception("command %s failed", command.id)
            self._last_error = str(exc)
            await self._cp.ack_command(command.id, CommandStatus.FAILED, str(exc))

    async def _dispatch(self, command: Command) -> Optional[str]:
        if command.type is CommandType.START:
            self._running = True
            return "running"
        if command.type is CommandType.STOP:
            self._running = False
            return "paused"
        if command.type is CommandType.FLATTEN:
            results = await self._executor.close_all()
            for result in results:
                await self._cp.record_trade(
                    {"source": "flatten", "string_code": result.string_code,
                     "position_id": result.position_id, "raw": result.raw}
                )
            return f"closed {len(results)} position(s)"
        if command.type in (CommandType.BUY, CommandType.SELL):
            return await self._manual_trade(command)
        raise ValueError(f"unhandled command type {command.type}")

    async def _manual_trade(self, command: Command) -> str:
        payload = command.payload
        symbol = payload.get("symbol")
        volume = payload.get("volume")
        if not symbol or volume is None:
            raise ValueError("manual trade requires 'symbol' and 'volume'")
        signal = TradeSignal(
            symbol=symbol,
            side=Side.BUY if command.type is CommandType.BUY else Side.SELL,
            volume=float(volume),
            stop_loss=payload.get("sl"),
            take_profit=payload.get("tp"),
            comment=payload.get("comment", "manual"),
        )
        result = await self._executor.execute(signal)
        await self._cp.record_trade(
            {"source": "manual", "string_code": result.string_code,
             "position_id": result.position_id, "raw": result.raw}
        )
        return f"{command.type.value} {symbol} {volume} -> {result.string_code}"

    async def _publish_state(self) -> None:
        state: Dict[str, Any] = {"running": self._running, "last_error": self._last_error}
        try:
            account = await self._executor.get_account_information()
            positions = await self._executor.get_positions()
            state.update(
                {
                    "balance": account.get("balance"),
                    "equity": account.get("equity"),
                    "currency": account.get("currency"),
                    "open_positions": len(positions),
                    "positions": positions,
                }
            )
        except Exception as exc:  # noqa: BLE001
            state["last_error"] = f"telemetry: {exc}"
            logger.warning("telemetry fetch failed: %s", exc)
        try:
            await self._cp.publish_state(state)
        except Exception:  # noqa: BLE001
            logger.exception("failed to publish state")
