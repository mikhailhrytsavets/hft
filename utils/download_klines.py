#!/usr/bin/env python3
"""Download historical 5-minute klines from Bybit.

Examples
--------
Download one month of BTCUSDT data::

    python -m utils.download_klines --symbol BTCUSDT --month 2025-05

Download an entire year (creates 12 monthly CSV files)::

    python -m utils.download_klines --symbol BTCUSDT --year 2025
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import pathlib
import time
import tomllib

from pybit.unified_trading import HTTP

from utils.retry import retry_rest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@retry_rest()
def _get_klines(http: HTTP, **params):
    """Wrapper around ``HTTP.get_kline`` with retries."""
    return http.get_kline(**params)


def collect(
    symbol: str,
    month: str,
    data_dir: pathlib.Path,
    http: HTTP | None = None,
    *,
    interval: int = 5,
) -> pathlib.Path:
    """Download one month of klines and save to CSV.

    Parameters
    ----------
    symbol:
        Trading pair, e.g. ``"BTCUSDT"``.
    month:
        Month in ``YYYY-MM`` format.
    data_dir:
        Directory where CSV files are written.
    http:
        Existing :class:`HTTP` client instance. If ``None``, a new one will be created.

    Returns
    -------
    :class:`pathlib.Path`
        Path to the written CSV file.
    """

    if http is None:
        http = HTTP(timeout=30)

    start_dt = dt.datetime.strptime(month + "-01", "%Y-%m-%d")
    next_month = (start_dt.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    end_ms = int(next_month.timestamp() * 1000)
    cur = int(start_dt.timestamp() * 1000)
    out_path = data_dir / f"{symbol}_{month}_kline{interval}m.csv"
    if out_path.exists():
        print(f"exists: {out_path}")
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        while cur < end_ms:
            resp = _get_klines(
                http,
                category="linear",
                symbol=symbol,
                interval=str(interval),
                start=cur,
                end=end_ms,
                limit=200,
            )
            klines = resp.get("result", {}).get("list", [])
            if not klines:
                break
            # API may return lists instead of dicts; convert for convenience
            if klines and isinstance(klines[0], list):
                keys = [
                    "start",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "turnover",
                ]
                klines = [dict(zip(keys, k)) for k in klines]
            klines.sort(key=lambda x: int(x.get("start") or x.get("t")))
            for k in klines:
                writer.writerow(
                    [
                        int(k.get("start") or k.get("t")),
                        k.get("open") or k.get("o"),
                        k.get("high") or k.get("h"),
                        k.get("low") or k.get("l"),
                        k.get("close") or k.get("c"),
                        k.get("volume") or k.get("v"),
                    ]
                )
            cur = int(klines[-1].get("start") or klines[-1].get("t")) + interval * 60 * 1000
            time.sleep(0.1)

    return out_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download Bybit kline data")
    sym = p.add_mutually_exclusive_group(required=True)
    sym.add_argument("--symbol", help="Trading pair, e.g. BTCUSDT")
    sym.add_argument("--symbols", help="Comma-separated trading pairs")
    sym.add_argument(
        "--all",
        action="store_true",
        help="Use symbols list from settings.toml",
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--month", help="Month YYYY-MM to download")
    group.add_argument("--start", help="Download from YYYY-MM-DD until today")
    group.add_argument("--year", type=int, help="Download all months of given year")
    p.add_argument("--interval", type=int, default=5, help="Kline interval in minutes")
    p.add_argument("--data-dir", default="data", help="Directory for CSV files")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    data_dir = pathlib.Path(args.data_dir)
    http = HTTP(timeout=30)

    if args.symbol:
        symbols = [args.symbol]
    elif args.symbols:
        symbols = [s.strip() for s in args.symbols.split(',') if s.strip()]
    else:
        with open(ROOT / "settings.toml", "rb") as f:
            symbols = tomllib.load(f)["bybit"]["symbols"]

    if args.year:
        for m in range(1, 13):
            month = f"{args.year}-{m:02d}"
            for sym in symbols:
                print(f"Downloading {sym} {month}…")
                collect(sym, month, data_dir, http, interval=args.interval)
        return

    if args.month:
        for sym in symbols:
            collect(sym, args.month, data_dir, http, interval=args.interval)
        return

    # --start logic: download starting from given date up to today
    start = dt.datetime.strptime(args.start, "%Y-%m-%d")
    today = dt.datetime.utcnow().replace(day=1)
    while start < today:
        month = start.strftime("%Y-%m")
        for sym in symbols:
            print(f"Downloading {sym} {month}…")
            collect(sym, month, data_dir, http, interval=args.interval)
        # move to next month
        start = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


if __name__ == "__main__":
    main()
