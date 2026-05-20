"""
Market Regime Detection

Determines market conditions to select appropriate strategy:
- TRENDING (ADX > 25): Use MA Crossover
- RANGING (ADX < 20): Use RSI Mean Reversion
- VOLATILE (High ATR): Use Bollinger Bands Breakout
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum

from ..models import MarketRegime, Candle


@dataclass
class RegimeIndicators:
    """Regime detection indicators"""
    adx: float  # Average Directional Index (0-100)
    atr: float  # Average True Range
    atr_percent: float  # ATR as % of price
    bb_width: float  # Bollinger Band width
    close_price: float


class RegimeManager:
    """
    Detects market regime and triggers strategy selection.
    
    Uses ADX (trend strength) and ATR (volatility) as primary indicators.
    """
    
    def __init__(
        self,
        adx_period: int = 14,
        atr_period: int = 14,
        bb_period: int = 20,
        trend_threshold: float = 25.0,  # ADX > 25 = TRENDING
        range_threshold: float = 20.0,  # ADX < 20 = RANGING
        volatility_threshold: float = 2.5  # ATR% > 2.5% = VOLATILE
    ):
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.bb_period = bb_period
        
        self.trend_threshold = trend_threshold
        self.range_threshold = range_threshold
        self.volatility_threshold = volatility_threshold
        
        self.current_regime = MarketRegime.UNKNOWN
        self.regime_history: List[tuple] = []  # [(timestamp, regime)]
    
    def detect_regime(
        self,
        candles: List[Candle],
        adx_value: float,
        atr_value: float,
        close_price: float
    ) -> MarketRegime:
        """
        Detect market regime from indicators.
        
        Args:
            candles: Recent candlestick data
            adx_value: Current ADX value (0-100)
            atr_value: Current ATR value
            close_price: Current price
        
        Returns:
            MarketRegime enum
        """
        if len(candles) < 2:
            return MarketRegime.UNKNOWN
        
        # Validate ADX range
        adx = max(0, min(100, adx_value))
        
        # Calculate ATR as percentage of price
        atr_percent = (atr_value / close_price * 100) if close_price > 0 else 0
        
        # Calculate Bollinger Bands width
        recent_closes = [c.close for c in candles[-self.bb_period:]]
        if len(recent_closes) >= 2:
            sma = sum(recent_closes) / len(recent_closes)
            std_dev = (sum((x - sma) ** 2 for x in recent_closes) / len(recent_closes)) ** 0.5
            bb_width = 4 * std_dev  # Bollinger Bands width (2 * 2 * std_dev)
        else:
            bb_width = 0
        
        # Regime detection logic
        # Priority: Volatility > Trending > Ranging
        
        if atr_percent > self.volatility_threshold:
            # High volatility takes precedence
            regime = MarketRegime.VOLATILE
        elif adx >= self.trend_threshold:
            # Strong directional trend
            regime = MarketRegime.TRENDING
        elif adx <= self.range_threshold:
            # Low trend strength = consolidation/ranging
            regime = MarketRegime.RANGING
        else:
            # ADX between thresholds = transitional
            regime = MarketRegime.RANGING  # Conservative: treat as ranging
        
        # Track regime changes
        if regime != self.current_regime:
            self.regime_history.append((datetime.now(), regime))
            self.current_regime = regime
        
        return regime
    
    def get_strategy_for_regime(self, regime: MarketRegime) -> str:
        """
        Get recommended strategy for current regime.
        
        Returns:
            Strategy name: 'ma_strategy', 'rsi_strategy', or 'bb_strategy'
        """
        strategy_map = {
            MarketRegime.TRENDING: "ma_strategy",      # MA Crossover
            MarketRegime.RANGING: "rsi_strategy",      # RSI Mean Reversion
            MarketRegime.VOLATILE: "bb_strategy",      # Bollinger Breakout
            MarketRegime.UNKNOWN: "ma_strategy",       # Default to MA
        }
        
        return strategy_map.get(regime, "ma_strategy")
    
    def should_trade_regime(self, regime: MarketRegime) -> bool:
        """
        Check if regime is suitable for trading.
        
        UNKNOWN regime = don't trade yet.
        """
        return regime != MarketRegime.UNKNOWN
    
    def get_regime_strength(self, adx_value: float) -> str:
        """
        Get qualitative strength of current trend.
        
        Returns: 'very_weak', 'weak', 'moderate', 'strong', 'very_strong'
        """
        adx = max(0, min(100, adx_value))
        
        if adx < 15:
            return "very_weak"
        elif adx < 25:
            return "weak"
        elif adx < 35:
            return "moderate"
        elif adx < 50:
            return "strong"
        else:
            return "very_strong"
    
    def get_regime_summary(
        self,
        adx_value: float,
        atr_value: float,
        close_price: float
    ) -> Dict[str, any]:
        """
        Get comprehensive regime summary.
        
        Returns:
            Dict with regime analysis
        """
        atr_percent = (atr_value / close_price * 100) if close_price > 0 else 0
        
        return {
            "regime": self.current_regime.value,
            "strategy": self.get_strategy_for_regime(self.current_regime),
            "adx": round(adx_value, 2),
            "atr": round(atr_value, 4),
            "atr_percent": round(atr_percent, 2),
            "trend_strength": self.get_regime_strength(adx_value),
            "trading_recommended": self.should_trade_regime(self.current_regime),
        }


# ============================================================================
# REGIME-AWARE SIGNAL FILTER
# ============================================================================

class RegimeAwareFilter:
    """
    Filters signals based on market regime.
    
    Prevents trading against strong trends or in unsuitable conditions.
    """
    
    def __init__(self, regime_manager: RegimeManager):
        self.regime_manager = regime_manager
    
    def should_accept_signal(
        self,
        signal_type: str,  # 'buy' or 'sell'
        regime: MarketRegime,
        adx_value: float,
        trend_direction: Optional[str] = None  # 'up' or 'down'
    ) -> bool:
        """
        Check if signal should be accepted in current regime.
        
        Filtering rules:
        - TRENDING: Only accept signals aligned with trend
        - RANGING: Accept mean-reversion signals
        - VOLATILE: Accept breakout signals
        """
        
        if not self.regime_manager.should_trade_regime(regime):
            return False
        
        if regime == MarketRegime.TRENDING:
            # In strong uptrend, only accept BUY signals
            # In strong downtrend, only accept SELL signals
            if trend_direction == "up" and signal_type.lower() != "buy":
                return False
            if trend_direction == "down" and signal_type.lower() != "sell":
                return False
        
        elif regime == MarketRegime.RANGING:
            # In ranging market, prefer mean-reversion (opposite direction)
            # This is already in RSI strategy logic
            pass
        
        elif regime == MarketRegime.VOLATILE:
            # In volatile market, accept breakout signals
            # Ensure ADX is not too low
            if adx_value < 15:  # Very weak trend = stay out
                return False
        
        return True


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    
    regime_manager = RegimeManager(
        trend_threshold=25.0,
        range_threshold=20.0,
        volatility_threshold=2.5
    )
    
    # Example regime detection
    test_cases = [
        (30, 2.5, 150.0, "Strong uptrend with moderate volatility"),
        (18, 1.0, 150.0, "Consolidation, low volatility"),
        (22, 4.5, 150.0, "Transitional, high volatility"),
    ]
    
    for adx, atr, price, description in test_cases:
        regime = regime_manager.detect_regime([], adx, atr, price)
        print(f"{description}")
        print(f"  ADX: {adx}, ATR: {atr}, Price: {price}")
        print(f"  Detected Regime: {regime.value}")
        print(f"  Recommended Strategy: {regime_manager.get_strategy_for_regime(regime)}")
        print()
