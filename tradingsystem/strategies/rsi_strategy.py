"""
RSI Mean Reversion Strategy

Best in: RANGING market regime (ADX < 20)

Logic:
- RSI: 14 period
- Entry: RSI < 30 (oversold) + price bounce
- Exit: RSI > 70 (overbought)
"""

from typing import List, Optional
from datetime import datetime

from ..models import Signal, SignalType, Candle, MarketRegime
from ..strategies.base import BaseStrategy


class RSIStrategy(BaseStrategy):
    """RSI Mean Reversion Strategy"""
    
    RSI_PERIOD = 14
    OVERSOLD = 30.0
    OVERBOUGHT = 70.0
    MAX_ADX = 20.0
    ATR_SL_MULT = 1.5
    ATR_TP_MULT = 2.5
    
    def analyze(
        self,
        candles: List[Candle],
        regime: MarketRegime,
        adx_value: float = 0,
        atr_value: float = 0,
        **kwargs
    ) -> Optional[Signal]:
        """Generate RSI mean reversion signal"""
        
        if not self._validate_candles(candles, self.RSI_PERIOD + 1):
            return None
        
        # Only trade in RANGING regime
        if regime.value != "ranging" or adx_value > self.MAX_ADX:
            return None
        
        closes = [c.close for c in candles]
        rsi = self._rsi(closes, self.RSI_PERIOD)
        
        if not rsi:
            return None
        
        current_price = closes[-1]
        if not atr_value:
            atr_value = self._atr_estimate(candles, 14)
        
        # BUY: RSI oversold with bounce
        if rsi < self.OVERSOLD:
            recent_low = min(c.low for c in candles[-5:])
            if current_price > recent_low * 1.01:
                return Signal(
                    strategy_name="rsi_strategy",
                    symbol=candles[-1].symbol,
                    signal_type=SignalType.BUY,
                    timestamp=datetime.now(),
                    price=current_price,
                    confidence=min(0.80, 0.4 + ((30 - rsi) / 30 * 0.4)),
                    regime=regime.value,
                    indicator_values={"rsi": round(rsi, 1)},
                    reason=f"RSI oversold at {rsi:.0f}"
                )
        
        # SELL: RSI overbought
        elif rsi > self.OVERBOUGHT:
            recent_high = max(c.high for c in candles[-5:])
            if current_price < recent_high * 0.99:
                return Signal(
                    strategy_name="rsi_strategy",
                    symbol=candles[-1].symbol,
                    signal_type=SignalType.SELL,
                    timestamp=datetime.now(),
                    price=current_price,
                    confidence=min(0.80, 0.4 + ((rsi - 70) / 30 * 0.4)),
                    regime=regime.value,
                    indicator_values={"rsi": round(rsi, 1)},
                    reason=f"RSI overbought at {rsi:.0f}"
                )
        
        return None
    
    @staticmethod
    def _rsi(prices: List[float], period: int) -> Optional[float]:
        """Calculate RSI"""
        if len(prices) < period + 1:
            return None
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [abs(d) if d < 0 else 0 for d in deltas[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100 if avg_gain > 0 else 50
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
