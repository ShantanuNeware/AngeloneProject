"""
Trading System Domain Models

Core dataclasses for:
- Market data (OHLCV candles)
- Trading signals
- Market regimes
"""

from .regime import MarketRegime
from .signal import Signal, SignalType
from .candle import Candle

__all__ = [
    "MarketRegime",
    "Signal",
    "SignalType",
    "Candle",
]
