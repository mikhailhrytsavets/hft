#!/usr/bin/env python3
"""
One-shot: download all 5-minute data for given year & symbols, then run
scripts/backtest_year.py and print KPI table.
"""
import argparse
import subprocess
import sys
import json
import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DL   = [sys.executable, "-m", "utils.download_klines"]
BT   = [sys.executable, "scripts/backtest_year.py"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--symbols", help="CSV list; default = [bybit].symbols")
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--equity", type=float, default=10_000)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out-dir",  default="backtests")
    args = ap.parse_args()

    if args.symbols:
        syms = [s.strip() for s in args.symbols.split(",")]
    else:
        with open(ROOT/"settings.toml", "rb") as f:
            syms = tomllib.load(f)["bybit"]["symbols"]

    # 1. download
    for s in syms:
        cmd = DL + ["--symbol", s, "--year", str(args.year),
                    "--interval", str(args.interval),
                    "--data-dir", args.data_dir]
        subprocess.run(cmd, check=True)

    # 2. backtest
    bt_cmd = BT + ["--symbols", ",".join(syms),
                   "--year", str(args.year),
                   "--data-dir", args.data_dir,
                   "--equity", str(args.equity),
                   "--out-dir", args.out_dir]
    subprocess.run(bt_cmd, check=True)

    # 3. pretty-print summary JSON
    summ = pathlib.Path(args.out_dir)/f"summary_{args.year}.json"
    print(json.dumps(json.loads(summ.read_text()), indent=2))

if __name__ == "__main__":
    main()
