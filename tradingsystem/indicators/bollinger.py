"""
Bollinger Bands Indicator
Measures volatility and identifies overbought/oversold conditions.

Bands:
- Upper Band = SMA + (StdDev * multiplier)
- Lower Band = SMA - (StdDev * multiplier)
- Middle Band = SMA

Usage:
- Price touching/crossing bands signals potential breakout
- Band width indicates volatility
- Band squeeze signals low volatility
"""

from typing import List, Optional, Tuple
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(next(parent for parent in Path(__file__).resolve().parents if (parent / "tradingsystem").exists())))


class BollingerBandsIndicator:
    """Calculate Bollinger Bands"""
    
    @staticmethod
    def calculate(
        close: List[float],
        period: int = 20,
        num_std_dev: float = 2.0
    ) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
        """
        Calculate Bollinger Bands
        
        Args:
            close: Close prices
            period: SMA period (default 20)
            num_std_dev: Number of standard deviations (default 2.0)
        
        Returns:
            Tuple of (upper_band, middle_band, lower_band)
        """
        if len(close) < period:
            return [None] * len(close), [None] * len(close), [None] * len(close)
        
        # Calculate SMA (middle band)
        sma = BollingerBandsIndicator._calculate_sma(close, period)
        
        # Calculate standard deviation
        std_devs = BollingerBandsIndicator._calculate_std_dev(close, period, sma)
        
        # Calculate bands
        upper_band = [None] * (period - 1)
        lower_band = [None] * (period - 1)
        
        for i in range(period - 1, len(close)):
            if sma[i] is not None and std_devs[i] is not None:
                upper_band.append(sma[i] + (std_devs[i] * num_std_dev))
                lower_band.append(sma[i] - (std_devs[i] * num_std_dev))
            else:
                upper_band.append(None)
                lower_band.append(None)
        
        return upper_band, sma, lower_band
    
    @staticmethod
    def _calculate_sma(close: List[float], period: int) -> List[Optional[float]]:
        """Calculate Simple Moving Average"""
        sma = [None] * (period - 1)
        
        for i in range(period - 1, len(close)):
            avg = sum(close[i - period + 1:i + 1]) / period
            sma.append(avg)
        
        return sma
    
    @staticmethod
    def _calculate_std_dev(close: List[float], period: int, sma: List[Optional[float]]) -> List[Optional[float]]:
        """Calculate standard deviation"""
        std_devs = [None] * (period - 1)
        
        for i in range(period - 1, len(close)):
            if sma[i] is None:
                std_devs.append(None)
                continue
            
            variance = sum((close[j] - sma[i]) ** 2 for j in range(i - period + 1, i + 1)) / period
            std_dev = variance ** 0.5
            std_devs.append(std_dev)
        
        return std_devs
    
    @staticmethod
    def get_band_width(upper: float, lower: float) -> float:
        """Calculate Bollinger Band width (volatility indicator)"""
        return upper - lower
    
    @staticmethod
    def get_band_width_percent(upper: float, lower: float, middle: float) -> float:
        """Get band width as percentage of middle band"""
        if middle == 0:
            return 0.0
        return ((upper - lower) / middle) * 100
    
    @staticmethod
    def is_squeezed(band_width_percent: float, squeeze_threshold: float = 5.0) -> bool:
        """Check if bands are squeezed (low volatility)"""
        return band_width_percent < squeeze_threshold


def main():
    """Run a standalone Bollinger Bands demo."""
    from trading_system.utils.standalone import print_json, sample_price_lists

    _, _, close = sample_price_lists()
    upper, middle, lower = BollingerBandsIndicator.calculate(close, period=20, num_std_dev=2.0)
    latest_upper = upper[-1]
    latest_middle = middle[-1]
    latest_lower = lower[-1]
    width_percent = BollingerBandsIndicator.get_band_width_percent(
        latest_upper or 0.0,
        latest_lower or 0.0,
        latest_middle or 0.0,
    )

    print_json(
        {
            "upper_band": latest_upper,
            "middle_band": latest_middle,
            "lower_band": latest_lower,
            "band_width_percent": width_percent,
            "is_squeezed": BollingerBandsIndicator.is_squeezed(width_percent),
        }
    )


if __name__ == "__main__":
    main()
