"""
MA Crossover Strategy (Trend Following)

Best in: TRENDING market regime (ADX > 25)

Logic:
- Fast MA: 9 period
- Slow MA: 21 period
- Entry: Price > fast MA with pullback confirmation
- Exit: Fast MA < slow MA (trend reversal)
"""

from typing import List, Optional
from datetime import datetime

from ..models import Signal, SignalType, Candle, MarketRegime
from ..strategies.base import BaseStrategy


class MAStrategy(BaseStrategy):
    """Moving Average Crossover Strategy"""
    
    # Simple hardcoded parameters - no complex config
    FAST_PERIOD = 9
    SLOW_PERIOD = 21
    MIN_ADX = 25.0
    ATR_SL_MULT = 1.5
    ATR_TP_MULT = 3.0
    
    def analyze(
        self,
        candles: List[Candle],
        regime: MarketRegime,
        adx_value: float = 0,
        atr_value: float = 0,
        **kwargs
    ) -> Optional[Signal]:
        """Generate MA crossover signal"""
        
        if not self._validate_candles(candles, self.SLOW_PERIOD + 1):
            return None
        
        # Only trade in TRENDING regime
        if regime.value != "trending" or adx_value < self.MIN_ADX:
            return None
        
        closes = [c.close for c in candles]
        fast_ma = self._sma(closes, self.FAST_PERIOD)
        slow_ma = self._sma(closes, self.SLOW_PERIOD)
        
        if not fast_ma or not slow_ma:
            return None
        
        current_price = closes[-1]
        prev_close = closes[-2]
        
        # Estimate ATR if not provided
        if not atr_value:
            atr_value = self._atr_estimate(candles, 14)
        
        # BUY: Golden cross with pullback
        if fast_ma > slow_ma:
            was_below = any(c.close < fast_ma for c in candles[-5:])
            
            if was_below and current_price > fast_ma:
                sl = current_price - (atr_value * self.ATR_SL_MULT)
                tp = current_price + (atr_value * self.ATR_TP_MULT)
                rr = (tp - current_price) / (current_price - sl)
                
                if rr > 1.5:
                    return Signal(
                        strategy_name="ma_strategy",
                        symbol=candles[-1].symbol,
                        signal_type=SignalType.BUY,
                        timestamp=datetime.now(),
                        price=current_price,
                        confidence=min(0.85, 0.5 + adx_value / 100 * 0.35),
                        regime=regime.value,
                        indicator_values={
                            "fast_ma": round(fast_ma, 2),
                            "slow_ma": round(slow_ma, 2),
                            "adx": round(adx_value, 1),
                            "rr": round(rr, 2),
                        },
                        reason="Golden cross with pullback"
                    )
        
        # SELL: Death cross
        elif fast_ma < slow_ma and prev_close > slow_ma:
            return Signal(
                strategy_name="ma_strategy",
                symbol=candles[-1].symbol,
                signal_type=SignalType.SELL,
                timestamp=datetime.now(),
                price=current_price,
                confidence=0.70,
                regime=regime.value,
                indicator_values={
                    "fast_ma": round(fast_ma, 2),
                    "slow_ma": round(slow_ma, 2),
                    "adx": round(adx_value, 1),
                },
                reason="Death cross - trend reversal"
            )
        
        return None
