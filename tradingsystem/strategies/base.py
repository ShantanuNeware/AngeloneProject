"""Strategy Base Class

All strategies implement the same analyze() interface.
"""

from abc import ABC, abstractmethod
from types import SimpleNamespace
from datetime import datetime
from typing import Optional, List

from ..models import Signal, SignalType, Candle, MarketRegime


class BaseStrategy(ABC):
    """Base class for all trading strategies"""
    
    def __init__(self, name: str):
        self.name = name
        # Default lightweight config object used by StrategyManager
        # Strategies may override by setting `self.config` explicitly
        self.config = SimpleNamespace(enabled=True)
    
    @abstractmethod
    def analyze(
        self,
        candles: List[Candle],
        regime: MarketRegime,
        adx_value: float = 0,
        atr_value: float = 0,
        **kwargs
    ) -> Optional[Signal]:
        """
        Analyze market and generate signal.
        
        Args:
            candles: Recent candlestick data (oldest to newest)
            regime: Current market regime
            adx_value: ADX trend strength (0-100)
            atr_value: ATR volatility value
        
        Returns:
            Signal if trade opportunity, else None
        """
        pass
    
    @staticmethod
    def _validate_candles(candles: List[Candle], min_count: int = 2) -> bool:
        """Check if we have enough candle data"""
        return len(candles) >= min_count
    
    @staticmethod
    def _sma(prices: List[float], period: int) -> Optional[float]:
        """Simple Moving Average"""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period
    
    @staticmethod
    def _ema(prices: List[float], period: int) -> Optional[float]:
        """Exponential Moving Average"""
        if len(prices) < period:
            return None
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[-period:]) / period
        
        for price in prices[-period + 1:]:
            ema = price * multiplier + ema * (1 - multiplier)
        
        return ema
    
    @staticmethod
    def _atr_estimate(candles: List[Candle], period: int = 14) -> float:
        """Estimate ATR from candles"""
        if len(candles) < period:
            period = len(candles)
        
        true_ranges = [c.true_range for c in candles[-period:]]
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0

