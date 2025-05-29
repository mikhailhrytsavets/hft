from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import tomllib
from dataclasses import dataclass, field


@dataclass
class SymbolParams:
    atr_period: int = 14
    bb_dev: float = 2.0
    dca_max: int = 2
    hedge_ratio: float = 0.50
    # additional fields stored dynamically
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # allow initialization from dict with unknown keys
        if isinstance(self.extra, dict):
            pass


def load_symbol_params(raw: Dict[str, Any]) -> Dict[str, SymbolParams]:
    out: Dict[str, SymbolParams] = {}
    for sym, data in raw.items():
        params = SymbolParams(**data)
        out[sym] = params
    return out


_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "settings.toml"
_raw = tomllib.load(open(_SETTINGS_FILE, "rb"))
SYMBOL_PARAMS = load_symbol_params(_raw.get("symbol_params", {}))
