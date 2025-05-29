#!/usr/bin/env python3
"""
Run:  python scripts/backtest_day.py --symbol BTCUSDT --date 2025-05-15 \
      --csv data/BTCUSDT_2025-05-15_kline5m.csv --equity 10000
"""
import argparse
import csv
import asyncio
import json
import pathlib
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.backtest import BacktestEngine


def load_bars(path: str):
    with open(path) as f:
        for ts, o, h, l, c, v in csv.reader(f):
            yield float(o), float(h), float(l), float(c), float(v), int(ts)


async def main(args) -> None:
    engine = BacktestEngine(symbol=args.symbol, equity=args.equity, log_equity=True)
    for row in load_bars(args.csv):
        await engine.feed_bar(*row)
    equity_path = pathlib.Path("backtests") / f"{args.symbol}_{args.date}_equity.csv"
    engine.save_equity_csv(equity_path)
    summary = engine.summary()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--csv", required=True)
    p.add_argument("--equity", type=float, default=10000)
    asyncio.run(main(p.parse_args()))
