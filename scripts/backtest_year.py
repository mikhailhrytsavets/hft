#!/usr/bin/env python3
"""
Run:
  python scripts/backtest_year.py --symbols BTCUSDT,ETHUSDT --year 2025 \
    --data-dir data --equity 10000 --out-dir backtests
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


async def backtest(
    symbol: str, csv_path: pathlib.Path, period: str, equity: float, out_dir: pathlib.Path
) -> dict:
    engine = BacktestEngine(symbol=symbol, equity=equity, log_equity=True)
    for row in load_bars(str(csv_path)):
        await engine.feed_bar(*row)
    engine.save_equity_csv(out_dir / f"{symbol}_{period}_equity.csv")
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
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_results = []
    aggregate_returns = []
    for month in range(1, 13):
        period = f"{args.year}-{month:02d}"
        for sym in symbols:
            csv_file = pathlib.Path(args.data_dir) / f"{sym}_{period}_kline5m.csv"
            if not csv_file.exists():
                continue
            res = await backtest(sym, csv_file, period, args.equity, out_dir)
            all_results.append(res)
            aggregate_returns.extend(res["returns"])
            print(
                f"{sym} {period} trades={res['trades']} pnl={res['pnl']:.2f} "
                f"sharpe={res['sharpe']:.2f} pf={res['pf']:.2f} dd={res['dd']:.2f}"
            )

    agg_equity = [0.0]
    for r in aggregate_returns:
        agg_equity.append(agg_equity[-1] + r)
    aggregate = {
        "trades": sum(r["trades"] for r in all_results),
        "pnl": agg_equity[-1],
        "sharpe": sharpe(agg_equity),
        "pf": profit_factor([{"pnl": r} for r in aggregate_returns]),
        "dd": max_drawdown(agg_equity),
    }
    print(
        f"YEAR trades={aggregate['trades']} pnl={aggregate['pnl']:.2f} "
        f"sharpe={aggregate['sharpe']:.2f} pf={aggregate['pf']:.2f} "
        f"dd={aggregate['dd']:.2f}"
    )
    summary_path = out_dir / f"summary_{args.year}.json"
    with open(summary_path, "w") as f:
        json.dump({"symbols": all_results, "aggregate": aggregate}, f, indent=2)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--equity", type=float, default=10000)
    p.add_argument("--out-dir", default="backtests")
    asyncio.run(main(p.parse_args()))
