"""
RSI Indicator (Relative Strength Index)
Momentum oscillator measuring speed and magnitude of price changes.

Range: 0-100
- RSI > 70: Overbought (potential reversal downward)
- RSI < 30: Oversold (potential reversal upward)
- RSI 40-60: Neutral/choppy market
- RSI > 80 or < 20: Extreme conditions

Usage:
- Mean reversion strategy: Buy oversold, Sell overbought
- Trend confirmation: RSI > 50 confirms uptrend
"""

from typing import List, Optional
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(next(parent for parent in Path(__file__).resolve().parents if (parent / "tradingsystem").exists())))


class RSIIndicator:
    """Calculate Relative Strength Index"""
    
    @staticmethod
    def calculate(
        close: List[float],
        period: int = 14
    ) -> List[Optional[float]]:
        """
        Calculate RSI
        
        Args:
            close: Close prices
            period: RSI period (default 14)
        
        Returns:
            List of RSI values (first period are None)
        """
        if len(close) < period + 1:
            return [None] * len(close)
        
        # Calculate price changes
        deltas = [close[i] - close[i - 1] for i in range(1, len(close))]
        
        # Separate gains and losses
        gains = [max(0, delta) for delta in deltas]
        losses = [max(0, -delta) for delta in deltas]
        
        rsi = [None] * period
        
        # First average gain and loss (SMA)
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        # Calculate RS and RSI
        if avg_loss == 0:
            rs = 100 if avg_gain > 0 else 0
        else:
            rs = avg_gain / avg_loss
        
        rsi.append(100 - (100 / (1 + rs)))
        
        # Subsequent RSI uses EMA smoothing
        for i in range(period + 1, len(close)):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            
            if avg_loss == 0:
                rs = 100 if avg_gain > 0 else 0
            else:
                rs = avg_gain / avg_loss
            
            rsi.append(100 - (100 / (1 + rs)))
        
        return rsi


def main():
    """Run a standalone RSI demo."""
    from trading_system.utils.standalone import print_json, sample_price_lists

    _, _, close = sample_price_lists()
    values = RSIIndicator.calculate(close, period=14)
    latest = values[-1]

    print_json(
        {
            "latest_rsi": latest,
            "state": "OVERBOUGHT" if latest and latest > 70 else "OVERSOLD" if latest and latest < 30 else "NEUTRAL",
            "computed_points": len([value for value in values if value is not None]),
        }
    )


if __name__ == "__main__":
    main()
