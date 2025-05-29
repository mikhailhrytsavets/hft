#!/usr/bin/env python3
"""
Run: python scripts/backtest_month.py --symbols BTCUSDT,ETHUSDT --month 2025-05 --data-dir data --equity 10000
"""
import argparse
import asyncio
import csv
import json
import os
import pathlib
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.backtest import BacktestEngine
from helpers.metrics import sharpe, profit_factor, max_drawdown


def load_bars(path: str):
    with open(path) as f:
        for ts, o, h, l, c, v in csv.reader(f):
            yield float(o), float(h), float(l), float(c), float(v), int(ts)


async def backtest(symbol: str, csv_path: pathlib.Path, equity: float):
    engine = BacktestEngine(symbol=symbol, equity=equity, log_equity=True)
    for row in load_bars(str(csv_path)):
        await engine.feed_bar(*row)
    equity_vals = [eq for _, eq in engine.equity_curve]
    returns = [equity_vals[i + 1] - equity_vals[i] for i in range(len(equity_vals) - 1)]
    return {
        "symbol": symbol,
        "trades": engine.trades,
        "pnl": equity_vals[-1] - equity_vals[0] if equity_vals else 0.0,
        "sharpe": sharpe(equity_vals),
        "pf": profit_factor([{"pnl": r} for r in returns]),
        "dd": max_drawdown(equity_vals),
        "returns": returns,
    }


async def main(args) -> None:
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    results = []
    aggregate_returns = []
    for sym in symbols:
        csv_file = pathlib.Path(args.data_dir) / f"{sym}_{args.month}_kline5m.csv"
        res = await backtest(sym, csv_file, args.equity)
        results.append(res)
        aggregate_returns.extend(res["returns"])
        print(
            f"{sym} trades={res['trades']} pnl={res['pnl']:.2f} "
            f"sharpe={res['sharpe']:.2f} pf={res['pf']:.2f} dd={res['dd']:.2f}"
        )

    agg_equity = [0.0]
    for r in aggregate_returns:
        agg_equity.append(agg_equity[-1] + r)
    aggregate = {
        "trades": sum(r["trades"] for r in results),
        "pnl": agg_equity[-1],
        "sharpe": sharpe(agg_equity),
        "pf": profit_factor([{"pnl": r} for r in aggregate_returns]),
        "dd": max_drawdown(agg_equity),
    }
    print(
        f"ALL trades={aggregate['trades']} pnl={aggregate['pnl']:.2f} "
        f"sharpe={aggregate['sharpe']:.2f} pf={aggregate['pf']:.2f} "
        f"dd={aggregate['dd']:.2f}"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", required=True)
    p.add_argument("--month", required=True)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--equity", type=float, default=10000)
    asyncio.run(main(p.parse_args()))
