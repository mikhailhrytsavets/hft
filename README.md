# hft

## Backtesting

Several helper scripts for offline backtesting are located in the `scripts` 
directory. They expect candle data in CSV format (for example
`BTCUSDT_2025-05_kline5m.csv`) stored in the directory specified by
`--data-dir`.

### Daily backtest

```bash
python scripts/backtest_day.py --symbol BTCUSDT --date 2025-05-15 \
  --csv data/BTCUSDT_2025-05-15_kline5m.csv --equity 10000
```

### Monthly backtest

```bash
python scripts/backtest_month.py --symbols BTCUSDT,ETHUSDT --month 2025-05 \
  --data-dir data --equity 10000 --out-dir backtests
```

This command writes equity curves for each symbol to `backtests/` and saves a
summary JSON file `summary_2025-05.json`.

### Yearly backtest

```bash
python scripts/backtest_year.py --symbols BTCUSDT,ETHUSDT --year 2025 \
  --data-dir data --equity 10000 --out-dir backtests
```

After completion all monthly equity CSV files and a yearly summary JSON will be
available in the output directory. These CSV files can be combined or analysed
in any spreadsheet application or with `pandas` for further research.

### Full-year one-liner

```bash
python scripts/fetch_and_backtest_year.py --year 2025 --interval 5 --equity 10000
```

Downloads all pairs listed in `[bybit].symbols`.

Produces `backtests/summary_2025.json` and monthly equity CSVs.

## Configuration

Runtime options are read from `settings.toml`.  The parameter
`candle_interval_sec` controls how long each aggregated candle lasts when the
engine warms up.  Decreasing this value shortens the warm‑up period without
changing any code.

Trailing stops are configured via `trailing_distance_percent` and
`trailing_step_percent`.  The distance sets how far from the current best price
the stop follows, while the step controls how much the price must move before
the stop is adjusted.
