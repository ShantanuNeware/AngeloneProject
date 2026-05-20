"""
Bollinger Bands Breakout Strategy

Best in: VOLATILE market regime

Logic:
- BB: 20 period, 2 std dev
- Entry: Price breaks above/below bands
- Volume confirmation required
"""

from typing import List, Optional, Tuple
from datetime import datetime

from ..models import Signal, SignalType, Candle, MarketRegime
from ..strategies.base import BaseStrategy


class BBStrategy(BaseStrategy):
    """Bollinger Bands Breakout Strategy"""
    
    BB_PERIOD = 20
    BB_STDEV = 2.0
    ATR_SL_MULT = 1.5
    ATR_TP_MULT = 2.0
    MIN_VOL_MULT = 1.2  # 20% above average
    
    def analyze(
        self,
        candles: List[Candle],
        regime: MarketRegime,
        adx_value: float = 0,
        atr_value: float = 0,
        **kwargs
    ) -> Optional[Signal]:
        """Generate Bollinger Bands breakout signal"""
        
        if not self._validate_candles(candles, self.BB_PERIOD + 1):
            return None
        
        closes = [c.close for c in candles]
        bb_upper, bb_mid, bb_lower = self._bb(closes, self.BB_PERIOD, self.BB_STDEV)
        
        if not bb_upper or not bb_lower:
            return None
        
        current = candles[-1]
        prev = candles[-2] if len(candles) > 1 else None
        
        if not atr_value:
            atr_value = self._atr_estimate(candles, 14)
        
        # BUY: Breakout above upper band
        if current.close > bb_upper and prev and prev.close < bb_upper:
            avg_vol = sum(c.volume for c in candles[-5:]) / 5
            if current.volume < avg_vol * self.MIN_VOL_MULT:
                return None
            
            return Signal(
                strategy_name="bb_strategy",
                symbol=current.symbol,
                signal_type=SignalType.BUY,
                timestamp=datetime.now(),
                price=current.close,
                confidence=0.75,
                regime=regime.value,
                indicator_values={
                    "bb_upper": round(bb_upper, 2),
                    "bb_lower": round(bb_lower, 2),
                },
                reason=f"Breakout above upper band {bb_upper:.2f}"
            )
        
        # SELL: Breakout below lower band
        elif current.close < bb_lower and prev and prev.close > bb_lower:
            avg_vol = sum(c.volume for c in candles[-5:]) / 5
            if current.volume < avg_vol * self.MIN_VOL_MULT:
                return None
            
            return Signal(
                strategy_name="bb_strategy",
                symbol=current.symbol,
                signal_type=SignalType.SELL,
                timestamp=datetime.now(),
                price=current.close,
                confidence=0.75,
                regime=regime.value,
                indicator_values={
                    "bb_upper": round(bb_upper, 2),
                    "bb_lower": round(bb_lower, 2),
                },
                reason=f"Breakout below lower band {bb_lower:.2f}"
            )
        
        return None
    
    @staticmethod
    def _bb(
        prices: List[float],
        period: int,
        stdev: float
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Calculate Bollinger Bands"""
        if len(prices) < period:
            return None, None, None
        
        recent = prices[-period:]
        mid = sum(recent) / period
        var = sum((p - mid) ** 2 for p in recent) / period
        std = var ** 0.5
        
        upper = mid + (stdev * std)
        lower = mid - (stdev * std)
        
        return upper, mid, lower
