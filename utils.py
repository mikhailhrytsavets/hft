from decimal import Decimal, ROUND_DOWN

def snap_qty(qty_raw: float, step: float) -> float:
    """
    Вернёт qty, округлённое ВНИЗ до ближайшего шага (step).
    """
    d_step = Decimal(str(step))
    d_raw  = Decimal(str(qty_raw))
    snapped = (d_raw // d_step) * d_step
    return float(snapped.quantize(d_step, ROUND_DOWN)) 
