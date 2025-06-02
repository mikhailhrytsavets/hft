from decimal import Decimal, ROUND_DOWN

def snap_qty(qty_raw: float, step: float) -> float:
    """
    Вернёт qty, округлённое ВНИЗ до ближайшего шага (step).
    """
    d_step = Decimal(str(step))
    d_raw  = Decimal(str(qty_raw))
    snapped = (d_raw // d_step) * d_step
    return float(snapped.quantize(d_step, ROUND_DOWN))


def format_price_change(current: float, reference: float) -> str:
    """Return formatted price change string ``"ref → cur (+x.xx%)"``."""
    if reference:
        pct = (current - reference) / reference * 100
    else:
        pct = 0.0
    sign = "+" if pct >= 0 else ""
    return f"{reference:.4f} → {current:.4f} ({sign}{pct:.2f}%)"
