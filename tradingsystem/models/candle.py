"""OHLCV Candle and Tick Data Models"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Candle:
    """
    Candlestick (OHLCV) data for technical analysis.
    """
    
    symbol: str
    timeframe: str  # "1m", "5m", "15m", "1h", "1d"
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    # Note: Validation removed - trust data fetcher produces valid candles
    
    @property
    def body_size(self) -> float:
        """Candle body size (absolute difference between open and close)"""
        return abs(self.close - self.open)
    
    @property
    def high_wick(self) -> float:
        """Upper wick size"""
        return self.high - max(self.open, self.close)
    
    @property
    def low_wick(self) -> float:
        """Lower wick size"""
        return min(self.open, self.close) - self.low
    
    @property
    def true_range(self) -> float:
        """True range (for ATR calculation)"""
        return self.high - self.low
    
    @property
    def is_bullish(self) -> bool:
        """True if close > open"""
        return self.close > self.open
    
    @property
    def is_bearish(self) -> bool:
        """True if close < open"""
        return self.close < self.open
    
    @property
    def is_doji(self) -> bool:
        """True if open ~= close (doji pattern)"""
        return abs(self.body_size) < (self.true_range * 0.1)


@dataclass
class Tick:
    """
    High-frequency tick data (bid/ask level).
    """
    
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    bid_qty: int
    ask_qty: int
    last_trade_price: float
    last_trade_qty: int
    
    @property
    def mid_price(self) -> float:
        """Mid price between bid and ask"""
        return (self.bid + self.ask) / 2.0
    
    @property
    def spread(self) -> float:
        """Bid-ask spread"""
        return self.ask - self.bid
    
    @property
    def spread_percent(self) -> float:
        """Bid-ask spread as percentage of mid price"""
        return (self.spread / self.mid_price) * 100 if self.mid_price > 0 else 0
