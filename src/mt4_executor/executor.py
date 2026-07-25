"""High-level trade execution on top of a connected MetaApi RPC connection."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Any, Dict, List, Optional

from mt4_executor.errors import TradeError, VolumeError
from mt4_executor.models import Side, TradeResult, TradeSignal


def normalize_volume(volume: float, spec: Dict[str, Any]) -> float:
    """Round ``volume`` down to the broker's volume step and clamp to min/max.

    Uses ``Decimal`` to avoid binary float drift (e.g. 0.1 + 0.2 artifacts) when
    snapping to the step grid. Rounds DOWN so a computed size never exceeds the
    intended risk. Raises ``VolumeError`` if the result falls below ``minVolume``.
    """
    step = spec.get("volumeStep")
    min_volume = spec.get("minVolume")
    max_volume = spec.get("maxVolume")

    if not step or step <= 0:
        raise VolumeError(f"Symbol spec has no usable volumeStep: {spec!r}")
    if volume <= 0:
        raise VolumeError(f"Volume must be positive, got {volume}")

    dv = Decimal(str(volume))
    dstep = Decimal(str(step))
    snapped = (dv / dstep).to_integral_value(rounding=ROUND_DOWN) * dstep

    if max_volume is not None and snapped > Decimal(str(max_volume)):
        snapped = Decimal(str(max_volume))

    if min_volume is not None and snapped < Decimal(str(min_volume)):
        raise VolumeError(
            f"Volume {volume} snaps to {snapped} which is below the symbol "
            f"minimum {min_volume}."
        )

    return float(snapped)


class TradeExecutor:
    """Executes trades against an already-connected MetaApi RPC connection.

    The connection lifecycle (provisioning, deploy, sync) is owned by
    :class:`~mt4_executor.connector.Mt4Connector`; this class only cares about
    a live connection object, which keeps its logic unit-testable with a mock.
    """

    def __init__(self, connection: Any) -> None:
        self._conn = connection

    async def get_account_information(self) -> Dict[str, Any]:
        return await self._conn.get_account_information()

    async def get_positions(self) -> List[Dict[str, Any]]:
        return await self._conn.get_positions()

    async def get_symbol_specification(self, symbol: str) -> Dict[str, Any]:
        return await self._conn.get_symbol_specification(symbol)

    async def execute(self, signal: TradeSignal, *, normalize: bool = True) -> TradeResult:
        """Open a market position from a :class:`TradeSignal`."""
        volume = signal.volume
        if normalize:
            spec = await self.get_symbol_specification(signal.symbol)
            volume = normalize_volume(volume, spec)

        opener = (
            self._conn.create_market_buy_order
            if signal.side is Side.BUY
            else self._conn.create_market_sell_order
        )
        try:
            response = await opener(
                signal.symbol,
                volume,
                signal.stop_loss,
                signal.take_profit,
                signal.options(),
            )
        except Exception as exc:  # noqa: BLE001 - re-raise as domain error
            raise self._to_trade_error(exc) from exc
        return TradeResult.from_response(response)

    async def market_buy(
        self,
        symbol: str,
        volume: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        **opts: Any,
    ) -> TradeResult:
        return await self.execute(
            TradeSignal(
                symbol=symbol,
                side=Side.BUY,
                volume=volume,
                stop_loss=stop_loss,
                take_profit=take_profit,
                comment=opts.get("comment"),
                client_id=opts.get("client_id"),
            )
        )

    async def market_sell(
        self,
        symbol: str,
        volume: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        **opts: Any,
    ) -> TradeResult:
        return await self.execute(
            TradeSignal(
                symbol=symbol,
                side=Side.SELL,
                volume=volume,
                stop_loss=stop_loss,
                take_profit=take_profit,
                comment=opts.get("comment"),
                client_id=opts.get("client_id"),
            )
        )

    async def modify_position(
        self,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> TradeResult:
        try:
            response = await self._conn.modify_position(position_id, stop_loss, take_profit)
        except Exception as exc:  # noqa: BLE001
            raise self._to_trade_error(exc) from exc
        return TradeResult.from_response(response)

    async def close_position(self, position_id: str) -> TradeResult:
        try:
            response = await self._conn.close_position(position_id)
        except Exception as exc:  # noqa: BLE001
            raise self._to_trade_error(exc) from exc
        return TradeResult.from_response(response)

    async def close_all(self, symbol: Optional[str] = None) -> List[TradeResult]:
        """Close every open position, optionally filtered to one symbol."""
        positions = await self.get_positions()
        results: List[TradeResult] = []
        for position in positions:
            if symbol and position.get("symbol") != symbol:
                continue
            results.append(await self.close_position(position["id"]))
        return results

    @staticmethod
    def _to_trade_error(exc: Exception) -> TradeError:
        if isinstance(exc, TradeError):
            return exc
        return TradeError(
            str(exc),
            string_code=getattr(exc, "stringCode", None),
            numeric_code=getattr(exc, "numericCode", None),
        )
