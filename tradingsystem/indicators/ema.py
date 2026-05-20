"""
EMA Indicator (Exponential Moving Average)
Weighted moving average that gives more importance to recent prices.

Advantages:
- Responds faster to price changes than SMA
- Better for trend-following strategies
- Standard for golden/death cross strategies
"""

from typing import List, Optional
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(next(parent for parent in Path(__file__).resolve().parents if (parent / "tradingsystem").exists())))


class EMAIndicator:
    """Calculate Exponential Moving Average"""
    
    @staticmethod
    def calculate(
        close: List[float],
        period: int
    ) -> List[Optional[float]]:
        """
        Calculate EMA
        
        Args:
            close: Close prices
            period: EMA period
        
        Returns:
            List of EMA values (first period-1 are None)
        """
        if len(close) < period:
            return [None] * len(close)
        
        ema = [None] * (period - 1)
        
        # First EMA is SMA
        sma = sum(close[:period]) / period
        ema.append(sma)
        
        # Multiplier for EMA calculation
        multiplier = 2 / (period + 1)
        
        # Calculate subsequent EMAs
        for i in range(period, len(close)):
            ema_value = close[i] * multiplier + ema[-1] * (1 - multiplier)
            ema.append(ema_value)
        
        return ema
    
    @staticmethod
    def get_ema_value(prev_ema: float, current_price: float, period: int) -> float:
        """
        Calculate next EMA value given previous EMA
        
        Useful for incremental calculations in live trading
        
        Args:
            prev_ema: Previous EMA value
            current_price: Current close price
            period: EMA period
        
        Returns:
            New EMA value
        """
        multiplier = 2 / (period + 1)
        return current_price * multiplier + prev_ema * (1 - multiplier)


def main():
    """Run a standalone EMA demo."""
    from trading_system.utils.standalone import print_json, sample_price_lists

    _, _, close = sample_price_lists()
    values = EMAIndicator.calculate(close, period=9)
    latest = values[-1]
    previous = values[-2]

    print_json(
        {
            "latest_ema": latest,
            "next_ema_projection": EMAIndicator.get_ema_value(previous or close[-2], close[-1], period=9),
            "computed_points": len([value for value in values if value is not None]),
        }
    )


if __name__ == "__main__":
    main()
