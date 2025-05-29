"""Lightweight settings loader with sensible defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import tomllib
from pydantic import BaseModel


class SymbolParams(BaseModel):
    atr_period: int = 14
    bb_dev: float = 2.0
    dca_max: int = 2
    hedge_ratio: float = 0.50


class Settings(BaseModel):
    symbol_params: Dict[str, SymbolParams] = {}


_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "settings.toml"


def load_symbol_params(raw: Dict[str, Any]) -> Dict[str, SymbolParams]:
    """Return mapping of symbol → :class:`SymbolParams` with defaults."""
    out: Dict[str, SymbolParams] = {}
    for sym, data in raw.items():
        out[sym] = SymbolParams(**data)
    return out


# parse file if present -------------------------------------------------------
if _SETTINGS_FILE.exists():
    data = tomllib.load(open(_SETTINGS_FILE, "rb"))
    sym_raw = data.get("symbol_params", {})
    settings = Settings(symbol_params=load_symbol_params(sym_raw))
else:  # pragma: no cover - file not found in tests
    settings = Settings()
