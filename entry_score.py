import math

def compute_entry_score(
    zscore: float,
    obi: float,
    vbd: float,
    spread_elasticity: float,
    taker_flow: float,
    volatility: float,
    weights: dict
) -> float:
    """
    Расчёт комплексного сигнала EntryScore
    """
    sign = math.copysign(1, zscore) if zscore != 0 else 0
    score = (
        weights.get("z", 0) * zscore +
        weights.get("obi", 0) * -obi +
        weights.get("vbd", 0) * -sign * vbd +
        weights.get("spread", 0) * spread_elasticity +
        weights.get("tflow", 0) * taker_flow -
        weights.get("volatility", 0) * volatility
)
    return score
