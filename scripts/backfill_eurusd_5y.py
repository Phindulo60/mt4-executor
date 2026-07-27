"""Mini experiment: pull ~5 years of EURUSD daily candles via MetaApi.

Pages MetaApi's historical candle API backwards (startTime = latest, walk
back) until it reaches the 5-year floor or the broker stops returning data.
Historical candles only need the account deployed + connected (no streaming
sync), so this is faster than the engine's full connect().

Run:  uv run python scripts/backfill_eurusd_5y.py
"""
from __future__ import annotations

import asyncio
import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mt4_executor.config import Settings
from mt4_executor.marketdata import MarketData

SYMBOL = os.getenv("EXP_SYMBOL", "EURUSD")
TIMEFRAME = os.getenv("EXP_TF", "1d")
YEARS = int(os.getenv("EXP_YEARS", "5"))
OUT = Path(os.path.expanduser("~/.aki/tmp")) / f"{SYMBOL}_{TIMEFRAME}_{YEARS}y.csv"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def main() -> None:
    from metaapi_cloud_sdk import MetaApi

    s = Settings.from_env()
    print(f"Symbol={SYMBOL} timeframe={TIMEFRAME} target={YEARS}y  server={s.server}")
    opts = {"region": s.region} if s.region else {}
    api = MetaApi(s.token, opts)

    accounts = await api.metatrader_account_api.get_accounts_with_infinite_scroll_pagination()
    account = next(
        (a for a in accounts if str(a.login) == str(s.login) and a.type.startswith("cloud")),
        None,
    )
    if account is None:
        raise SystemExit(f"No cloud MetaApi account found for login {s.login}")

    print("Deploying + waiting for broker connection...")
    await account.deploy()
    await account.wait_connected()

    md = MarketData(None, account=account)
    floor = datetime.now(timezone.utc) - timedelta(days=365 * YEARS)
    start = None  # None = latest
    seen: dict = {}
    requests = 0

    while True:
        batch = await md.get_candles(SYMBOL, TIMEFRAME, 1000, start_time=start)
        requests += 1
        if not batch:
            print(f"  request {requests}: empty -> broker has no more history")
            break
        for c in batch:
            seen[_aware(c.time)] = c
        oldest = _aware(batch[0].time)
        newest = _aware(batch[-1].time)
        print(f"  request {requests}: +{len(batch)} candles  [{oldest.date()} .. {newest.date()}]  total={len(seen)}")
        if oldest <= floor:
            break
        next_start = oldest - timedelta(days=1)
        if start is not None and next_start >= start:
            print("  no backward progress -> stopping")
            break
        start = next_start

    candles = sorted(seen.values(), key=lambda c: _aware(c.time))
    if not candles:
        print("No candles returned.")
        return

    earliest = _aware(candles[0].time)
    latest = _aware(candles[-1].time)
    span_days = (latest - earliest).days

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "tick_volume", "volume"])
        for c in candles:
            w.writerow([_aware(c.time).isoformat(), c.open, c.high, c.low, c.close, c.tick_volume, c.volume])

    print("\n=== RESULT ===")
    print(f"candles:   {len(candles)}")
    print(f"earliest:  {earliest.isoformat()}")
    print(f"latest:    {latest.isoformat()}")
    print(f"span:      {span_days} days (~{span_days / 365:.2f} years)")
    print(f"requests:  {requests}")
    print(f"csv:       {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
