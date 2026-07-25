# mt4-executor

A small, standalone, autonomous **MT4 trade-execution connector** built on
[MetaApi.cloud](https://metaapi.cloud). It provisions/connects your MT4 broker
account through MetaApi's managed cloud terminal (no Windows box, no Wine) and
gives you a clean async API + CLI to open, modify, and close market positions.

> This project is intentionally decoupled from any signal-generation system.
> It only executes trades it is told to execute.

## Why MetaApi

MT4 has no native cloud/Linux execution path — every alternative needs a live
MT4 terminal running 24/7 (Windows, or Wine on Linux). MetaApi hosts that
terminal for you and exposes a stable REST/WebSocket API, so this connector
runs anywhere Python runs.

## Setup

1. In the MetaApi dashboard, create an **API access token**.
2. Have your MT4 **login**, **password** (master, not investor — investor is
   read-only), and exact **server name** from your terminal ready.

```bash
cd mt4-executor
uv venv && uv sync --extra dev     # or: python -m venv .venv && pip install -e ".[dev]"
cp .env.example .env               # then fill in the four required values
```

Required env vars: `METAAPI_TOKEN`, `MT_LOGIN`, `MT_PASSWORD`, `MT_SERVER`.
Optional: `MT_ACCOUNT_NAME`, `MT_MAGIC`, `METAAPI_REGION`.

## CLI

```bash
mt4-executor account                              # account info
mt4-executor positions                            # open positions
mt4-executor buy EURUSD 0.10 --sl 1.05 --tp 1.15  # market buy
mt4-executor sell GBPUSD 0.05                      # market sell
mt4-executor close <position_id>                  # close one
mt4-executor close-all --symbol EURUSD            # close all (optional filter)

# Cost control: undeploy the MetaApi account when done (stops deployed-account
# billing; next run redeploys + resyncs, which is slower).
mt4-executor account --undeploy-after
```

## Autonomous loop

The loop wires **market data -> strategy -> execution** and runs on an interval:

```bash
# One pass over the symbols, then exit (great for a smoke test on demo)
mt4-executor run --symbol EURUSD --once

# Continuous: poll every 60s across two symbols on the 1h timeframe
mt4-executor run --symbol EURUSD --symbol GBPUSD --timeframe 1h --interval 60
```

Out of the box it uses `HoldStrategy` (a placeholder that never trades), so
`run` will fetch market data every interval and decide to do nothing. That
proves the plumbing end-to-end. To make it trade, implement the `Strategy`
protocol and pass it into `TradingLoop`:

```python
from mt4_executor import (
    Settings, Mt4Connector, MarketData, TradeExecutor,
    TradingLoop, LoopConfig, Strategy, MarketSnapshot, TradeSignal, Side,
)

class MyStrategy:  # implements the Strategy protocol
    async def decide(self, snap: MarketSnapshot):
        if snap.latest and snap.latest.close > snap.candles[0].close:
            return TradeSignal(symbol=snap.symbol, side=Side.BUY, volume=0.01)
        return None

async def main():
    connector = Mt4Connector(Settings.from_env())
    async with connector as connection:
        loop = TradingLoop(
            MarketData(connection, account=connector.account),
            TradeExecutor(connection),
            MyStrategy(),
            LoopConfig(symbols=["EURUSD"], timeframe="1h", poll_interval=60),
        )
        await loop.run_forever()   # Ctrl-C / SIGTERM stops it cleanly
```

The loop deliberately contains **no trading or risk logic** - it only ties the
layers together, isolates per-symbol errors so one failure does not kill the
loop, and stops gracefully on SIGINT/SIGTERM. Strategy and risk sizing are the
next pieces to build.

## Billing note

MetaApi bills for the time an account is **deployed** (the managed terminal
running in their cloud), prorated — **independent of whether you place any
trades**. An idle-but-deployed account still consumes balance. For an always-on
autonomous setup, keep it deployed (fast execution). For occasional runs, use
`--undeploy-after` (CLI) or `Mt4Connector(settings, undeploy_on_close=True)`
to release the resource between sessions.

Volume is normalized to the broker's `volumeStep`/`minVolume`/`maxVolume` by
default (rounded **down** so size never exceeds intent). Use `--no-normalize`
to send the raw value.

## Programmatic use

```python
import asyncio
from mt4_executor import Settings, Mt4Connector, TradeExecutor, TradeSignal, Side

async def main():
    settings = Settings.from_env()
    async with Mt4Connector(settings) as connection:
        ex = TradeExecutor(connection)
        result = await ex.execute(
            TradeSignal(symbol="EURUSD", side=Side.BUY, volume=0.10,
                        stop_loss=1.05, take_profit=1.15, comment="demo")
        )
        print(result.succeeded, result.raw)

asyncio.run(main())
```

## Architecture

| Module | Responsibility |
|---|---|
| `config.py` | `Settings.from_env()` — validated env-driven config |
| `connector.py` | `Mt4Connector` — MetaApi lifecycle (provision → deploy → connect → sync), async context manager |
| `executor.py` | `TradeExecutor` — market buy/sell/close/modify + `normalize_volume()` |
| `marketdata.py` | `MarketData` — latest price/candle + historical candles |
| `strategy.py` | `Strategy` protocol + `HoldStrategy` placeholder (the decision seam) |
| `runner.py` | `TradingLoop` — `run_once()` / `run_forever()` autonomous loop |
| `models.py` | `Side`, `TradeSignal`, `TradeResult`, `Candle`, `Price` |
| `errors.py` | Domain exceptions (`ConfigError`, `ConnectorError`, `TradeError`, `VolumeError`) |

The connector owns the network lifecycle; the executor only needs a live
connection object, which keeps its logic unit-testable without any network.

## Testing

```bash
uv run pytest        # or: .venv/bin/pytest
```

Tests mock the MetaApi connection — they never hit the network or place real trades.

## Built so far

- **Market data** (`MarketData`) - price, latest candle, historical candles.
- **Execution** (`TradeExecutor`) - market buy/sell/close/modify + volume normalization.
- **Autonomous loop** (`TradingLoop`) - polls data and executes decisions on an interval.

## Still to build (deliberately)

- **Strategy** - the actual decision logic. Currently a `HoldStrategy` placeholder;
  implement the `Strategy` protocol to make it trade.
- **Risk-based position sizing** - compute lot size from a risk amount + stop
  distance. Omitted for now: it needs reliable per-lot monetary value with
  account-currency conversion, and a half-correct version is dangerous.
- **Guardrails** - max daily loss, max open positions, kill-switch, restart dedup.
  Build these before any live (non-demo) autonomous run.

## Safety notes

- Start on a **demo** account and verify behavior before going live.
- Keeping the account deployed (default) means faster execution but MetaApi
  bills the deployed resource. `Mt4Connector.close(undeploy=True)` frees it.
