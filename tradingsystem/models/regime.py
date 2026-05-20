"""Market Regime Classification"""

from enum import Enum


class MarketRegime(Enum):
    """
    Market regime determines which strategy to use.
    
    TRENDING: Strong directional movement (ADX > 25)
        → Use MA Crossover strategy
        
    RANGING: Consolidation/sideways movement (ADX < 20)
        → Use RSI Mean Reversion strategy
        
    VOLATILE: High uncertainty/volatility spike
        → Use Bollinger Bands Breakout strategy
    """
    
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value.upper()
