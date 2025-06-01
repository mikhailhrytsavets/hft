from datetime import datetime, timedelta
from app.notifier import notify_telegram


def strfdelta(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


async def log_entry(
    symbol: str,
    direction: str,
    qty: float,
    reason: str,
    features: dict[str, float],
    passed_filters: list[str],
    entry_type: str = "score",
) -> None:
    """Send detailed entry log to Telegram."""
    emoji = "\U0001F4E5"  # inbox tray
    feature_line = ", ".join([f"{k}={v:.2f}" for k, v in features.items()])
    filter_line = ", ".join(passed_filters) if passed_filters else "none"

    reason_line = (
        f"score={features.get('z', 0):.2f} {'<' if direction == 'LONG' else '>'} thr ({reason})"
        if entry_type == "score"
        else f"BounceEntry: {reason}"
    )

    await notify_telegram(
        f"{emoji} Entry {symbol} {direction} qty={qty:.2f}\n"
        f"\U0001F4CA Reason: {reason_line}\n"
        f"\u2705 Filters passed: {filter_line}\n"
        f"\U0001F4C8 Features: {feature_line}"
    )


async def log_exit(
    symbol: str,
    side: str,
    exit_reason: str,
    avg_price: float,
    exit_price: float,
    opened_at: datetime,
) -> None:
    """Send detailed exit log to Telegram."""
    pnl = exit_price - avg_price if side == "Buy" else avg_price - exit_price
    pnl_pct = 100 * pnl / avg_price
    duration = datetime.utcnow() - opened_at

    reason_map = {
        "TP": "Take-Profit",
        "SOFT_SL": "ATR stop",
        "HARD_SL": "Hard SL %",
        "TRAILING": "Trailing stop",
    }
    reason_text = reason_map.get(exit_reason, exit_reason)

    await notify_telegram(
        f"\U0001F534 {exit_reason} {symbol}\n"
        f"\U0001F4C9 Reason: {reason_text}\n"
        f"\U0001F4B0 PnL: {pnl:.2f} USDT ({pnl_pct:.2f}%)\n"
        f"\U0001F551 Duration: {strfdelta(duration)}"
    )

