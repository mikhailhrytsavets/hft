from pydantic import BaseModel
import tomllib
from pathlib import Path

class BybitSettings(BaseModel):
    api_key: str
    api_secret: str
    symbols: list[str]
    testnet: bool = False
    demo: bool = False
    place_orders: bool = True
    channel_type: str = "linear"

class TradingSettings(BaseModel):
    """Trading parameters including optional hybrid‑strategy fields.

    The class defines standard risk and DCA settings and also supports the
    following hybrid options used by ``HybridStrategyEngine``:

    ``strategy_mode``,
    ``enable_mm``, ``mm_spread_percent``, ``mm_refresh_seconds``,
    ``enable_mom_filter``, ``momentum_period``, ``use_ml_scoring``,
    ``use_atr_stop``, ``atr_stop_multiplier``, ``hard_sl_percent``,
    ``enable_stat_arb``, ``stat_arb_entry_z``, ``stat_arb_exit_z`` and
    ``stat_arb_stop_z``.
    """
    leverage: int
    initial_risk_percent: float
    dca_risk_multiplier: float
    dca_step_percent: float = 0.3
    max_dca_levels: int
    take_profit_percent: float
    soft_sl_percent: float
    soft_sl_minutes: int = 0  # 0 disables time-based soft stop
    fallback_qty: float = 0.0
    max_position_risk_percent: float = 5.0
    enable_risk_cap: bool = True
    enable_position_timeout: bool = False
    max_position_minutes: int = 0
    enable_rsi_filter: bool = False
    enable_time_filter: bool = False
    trade_start_hour: int = 0
    trade_end_hour: int = 24
    enable_rsi_dca: bool = False
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    break_even_after_percent: float = 0.0
    break_even_after_minutes: int = 0
    min_profit_to_be: float = 0.10
    max_dca_drawdown_percent: float = 0.0
    dca_min_interval_minutes: int = 5
    enable_dca_adx_filter: bool = False
    dca_adx_threshold: float = 25.0
    dca_step_multiplier: float = 1.0
    enable_dca_spread_filter: bool = False
    dca_spread_threshold: float = 3.0
    enable_dca_vbd_filter: bool = False
    dca_vbd_threshold: float = 0.5
    use_adx_filter: bool = False
    adx_period: int = 14
    adx_threshold: float = 25.0
    use_htf_filter: bool = False
    htf_interval: str = "1h"
    enable_trend_mode: bool = False
    trend_adx_threshold: float = 25.0
    enable_hedging: bool = False
    max_hedges: int = 1
    hedge_delay_seconds: float = 0.0
    candle_interval_sec: int = 15
    enable_hedge_adx_filter: bool = False
    hedge_adx_threshold: float = 20.0
    hedge_size_ratio: float = 1.0
    tp1_percent: float | None = 0.5
    tp1_close_ratio: float = 0.5
    tp2_percent: float | None = None
    tp2_close_ratio: float | None = 0.3
    trailing_distance_percent: float = 0.2
    trailing_step_percent: float = 0.05
    # ---- hybrid strategy additions ----
    strategy_mode: str = "basic"
    enable_mm: bool = False
    mm_spread_percent: float = 0.2
    mm_refresh_seconds: int = 10
    enable_mom_filter: bool = False
    momentum_period: int = 5
    use_ml_scoring: bool = False
    use_atr_stop: bool = False
    atr_stop_multiplier: float = 1.5
    hard_sl_percent: float = 2.0
    enable_stat_arb: bool = False
    stat_arb_entry_z: float = 2.0
    stat_arb_exit_z: float = 0.5
    stat_arb_stop_z: float = 4.0

class RiskSettings(BaseModel):
    daily_drawdown_percent: float
    enable_daily_drawdown_guard: bool = True
    daily_profit_percent: float = 0.0
    enable_daily_profit_guard: bool = True
    max_open_positions: int = 0
    max_total_volume: float = 0.0
    daily_trades_limit: int = 0
    enable_daily_trades_guard: bool = False

class TelegramSettings(BaseModel):
    bot_token: str
    chat_id: str

class EntryScoreSettings(BaseModel):
    weights: dict
    long_threshold: float
    short_threshold: float
    threshold_k: float = 2.0
    symbol_weights: dict[str, dict] = {}
    symbol_threshold_k: dict[str, float] = {}

class MultiTFSettings(BaseModel):
    enable: bool = False
    intervals: list[str] = []
    weights: dict[str, float] = {}
    update_seconds: int = 30
    trend_confirm_bars: int = 3

class SymbolParams(BaseModel):
    atr_period: int = 14
    bb_dev: float = 2.0
    dca_max: int = 2
    hedge_ratio: float = 0.50
    ref_symbol: str | None = None

class Settings(BaseModel):
    bybit: BybitSettings
    trading: TradingSettings
    risk: RiskSettings
    telegram: TelegramSettings
    entry_score: EntryScoreSettings
    multi_tf: MultiTFSettings = MultiTFSettings()
    symbol_params: dict[str, SymbolParams] = {}


_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "settings.toml"
try:
    with open(_SETTINGS_FILE, "rb") as f:
        raw = tomllib.load(f)
except tomllib.TOMLDecodeError as exc:
    raise RuntimeError(f"Failed to parse {_SETTINGS_FILE}: {exc}") from exc
sym_raw = raw.pop("symbol_params", {})
settings = Settings(**raw, symbol_params={k: SymbolParams(**v) for k, v in sym_raw.items()})
