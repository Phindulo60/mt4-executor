"""Command-line interface for the MT4 executor."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from typing import List, Optional

from mt4_executor.config import Settings
from mt4_executor.connector import Mt4Connector
from mt4_executor.errors import Mt4ExecutorError
from mt4_executor.executor import TradeExecutor
from mt4_executor.marketdata import MarketData
from mt4_executor.models import Side, TradeSignal
from mt4_executor.controlplane import SupabaseControlPlane
from mt4_executor.engine import Engine
from mt4_executor.runner import LoopConfig, TradingLoop
from mt4_executor.strategy import HoldStrategy


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mt4-executor",
        description="Standalone autonomous MT4 trade executor (MetaApi.cloud).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--undeploy-after",
        action="store_true",
        help="Undeploy the MetaApi account after the command finishes to stop "
        "deployed-account billing (next run must redeploy + resync).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("account", help="Print account information")
    sub.add_parser("positions", help="List open positions")

    for side in ("buy", "sell"):
        p = sub.add_parser(side, help=f"Open a market {side} order")
        p.add_argument("symbol")
        p.add_argument("volume", type=float)
        p.add_argument("--sl", type=float, default=None, help="Stop loss price")
        p.add_argument("--tp", type=float, default=None, help="Take profit price")
        p.add_argument("--comment", default=None)
        p.add_argument("--client-id", default=None)
        p.add_argument("--no-normalize", action="store_true", help="Skip volume normalization")

    p_close = sub.add_parser("close", help="Close a single position by id")
    p_close.add_argument("position_id")

    p_close_all = sub.add_parser("close-all", help="Close all open positions")
    p_close_all.add_argument("--symbol", default=None, help="Limit to one symbol")

    p_run = sub.add_parser(
        "run",
        help="Run the autonomous market-data->execute loop (placeholder HoldStrategy)",
    )
    p_run.add_argument(
        "--symbol", dest="symbols", action="append", required=True,
        help="Symbol to trade; repeat for multiple (e.g. --symbol EURUSD --symbol GBPUSD)",
    )
    p_run.add_argument("--timeframe", default="1h", help="Candle timeframe (default 1h)")
    p_run.add_argument("--interval", type=float, default=60.0, help="Poll interval seconds")
    p_run.add_argument("--history", type=int, default=100, help="Candles per snapshot")
    p_run.add_argument("--once", action="store_true", help="Run one pass and exit")

    p_eng = sub.add_parser(
        "engine",
        help="Run the always-on engine: polls commands from Supabase + publishes telemetry",
    )
    p_eng.add_argument(
        "--symbol", dest="symbols", action="append", required=True,
        help="Symbol the strategy loop watches; repeat for multiple",
    )
    p_eng.add_argument("--timeframe", default="1h")
    p_eng.add_argument("--interval", type=float, default=5.0, help="Engine tick seconds")
    p_eng.add_argument("--history", type=int, default=100)
    p_eng.add_argument(
        "--start-running", action="store_true",
        help="Begin with the strategy loop active (default: paused, start via the site)",
    )

    return parser


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


async def _run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    connector = Mt4Connector(settings, undeploy_on_close=args.undeploy_after)
    async with connector as connection:
        executor = TradeExecutor(connection)

        if args.command == "account":
            _print(await executor.get_account_information())
        elif args.command == "positions":
            _print(await executor.get_positions())
        elif args.command in ("buy", "sell"):
            signal = TradeSignal(
                symbol=args.symbol,
                side=Side.BUY if args.command == "buy" else Side.SELL,
                volume=args.volume,
                stop_loss=args.sl,
                take_profit=args.tp,
                comment=args.comment,
                client_id=args.client_id,
            )
            result = await executor.execute(signal, normalize=not args.no_normalize)
            _print(result.raw)
        elif args.command == "close":
            result = await executor.close_position(args.position_id)
            _print(result.raw)
        elif args.command == "close-all":
            results = await executor.close_all(symbol=args.symbol)
            _print([r.raw for r in results])
        elif args.command == "run":
            await _run_loop(connection, connector, args)
        elif args.command == "engine":
            await _run_engine(connection, connector, args)
    return 0


async def _run_engine(connection, connector: Mt4Connector, args: argparse.Namespace) -> None:
    market_data = MarketData(connection, account=connector.account)
    executor = TradeExecutor(connection)
    strategy = HoldStrategy()
    config = LoopConfig(
        symbols=args.symbols,
        timeframe=args.timeframe,
        poll_interval=args.interval,
        history_size=args.history,
    )
    loop = TradingLoop(market_data, executor, strategy, config)
    control_plane = SupabaseControlPlane.from_env()
    engine = Engine(
        loop, executor, control_plane,
        poll_interval=args.interval,
        start_running=args.start_running,
    )

    running = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            running.add_signal_handler(sig, engine.stop)
        except NotImplementedError:  # pragma: no cover - non-Unix
            pass
    try:
        await engine.run_forever()
    finally:
        await control_plane.close()


async def _run_loop(connection, connector: Mt4Connector, args: argparse.Namespace) -> None:
    market_data = MarketData(connection, account=connector.account)
    executor = TradeExecutor(connection)
    strategy = HoldStrategy()
    config = LoopConfig(
        symbols=args.symbols,
        timeframe=args.timeframe,
        poll_interval=args.interval,
        history_size=args.history,
    )
    loop = TradingLoop(market_data, executor, strategy, config)

    if args.once:
        results = await loop.run_once()
        _print([r.raw for r in results])
        return

    running = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            running.add_signal_handler(sig, loop.stop)
        except NotImplementedError:  # pragma: no cover - non-Unix
            pass
    await loop.run_forever()


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return asyncio.run(_run(args))
    except Mt4ExecutorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
