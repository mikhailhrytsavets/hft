from __future__ import annotations

import argparse
import asyncio
import csv

from src.core.data import Bar
from src.symbol_engine import SymbolEngine


async def _run_file(path: str) -> None:
    se = SymbolEngine("TEST")
    with open(path) as f:
        for ts, o, h, l, c, v in csv.reader(f):
            bar = Bar(float(o), float(h), float(l), float(c), float(v), int(ts), int(ts) + 300)
            await se._on_bar(bar)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test")
    args = parser.parse_args()
    if args.test:
        asyncio.run(_run_file(args.test))


if __name__ == "__main__":
    main()
