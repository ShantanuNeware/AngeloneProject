"""
ADX Indicator (Average Directional Index)
Measures trend strength and direction.
- ADX > 25: Strong trend
- ADX 20-25: Moderate trend
- ADX < 20: Weak trend / ranging market
"""

from typing import List, Optional
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(next(parent for parent in Path(__file__).resolve().parents if (parent / "tradingsystem").exists())))


class ADXIndicator:
    """Calculate Average Directional Index"""
    
    @staticmethod
    def calculate(
        high: List[float],
        low: List[float],
        close: List[float],
        period: int = 14
    ) -> List[Optional[float]]:
        """
        Calculate ADX
        
        Args:
            high: High prices
            low: Low prices
            close: Close prices
            period: ADX period (default 14)
        
        Returns:
            List of ADX values (first period-1 are None)
        """
        if len(high) < period or len(low) < period or len(close) < period:
            return [None] * len(close)
        
        # Calculate True Range
        tr = ADXIndicator._calculate_tr(high, low, close)
        
        # Calculate Directional Movement
        plus_dm, minus_dm = ADXIndicator._calculate_dm(high, low, period)
        
        # Calculate Directional Indicators
        plus_di = ADXIndicator._calculate_di(plus_dm, tr, period)
        minus_di = ADXIndicator._calculate_di(minus_dm, tr, period)
        
        # Calculate ADX
        adx = ADXIndicator._calculate_adx(plus_di, minus_di, period)
        
        return adx
    
    @staticmethod
    def _calculate_tr(high: List[float], low: List[float], close: List[float]) -> List[float]:
        """Calculate True Range"""
        tr = []
        for i in range(len(high)):
            if i == 0:
                tr.append(high[i] - low[i])
            else:
                tr_value = max(
                    high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1])
                )
                tr.append(tr_value)
        return tr
    
    @staticmethod
    def _calculate_dm(high: List[float], low: List[float], period: int):
        """Calculate Directional Movement"""
        plus_dm = [0.0] * len(high)
        minus_dm = [0.0] * len(high)
        
        for i in range(1, len(high)):
            up_move = high[i] - high[i - 1]
            down_move = low[i - 1] - low[i]
            
            if up_move > down_move and up_move > 0:
                plus_dm[i] = up_move
            else:
                plus_dm[i] = 0
            
            if down_move > up_move and down_move > 0:
                minus_dm[i] = down_move
            else:
                minus_dm[i] = 0
        
        return plus_dm, minus_dm
    
    @staticmethod
    def _calculate_di(dm: List[float], tr: List[float], period: int) -> List[float]:
        """Calculate Directional Indicator"""
        di = [None] * (period - 1)
        
        # Sum first period
        sum_dm = sum(dm[:period])
        sum_tr = sum(tr[:period])
        
        if sum_tr > 0:
            di.append((sum_dm / sum_tr) * 100)
        else:
            di.append(0.0)
        
        # Smoothed calculation
        for i in range(period + 1, len(dm)):
            sum_dm = sum_dm - dm[i - period] + dm[i]
            sum_tr = sum_tr - tr[i - period] + tr[i]
            
            if sum_tr > 0:
                di.append((sum_dm / sum_tr) * 100)
            else:
                di.append(0.0)
        
        return di
    
    @staticmethod
    def _calculate_adx(plus_di: List[float], minus_di: List[float], period: int) -> List[Optional[float]]:
        """Calculate ADX from DI values"""
        adx = [None] * len(plus_di)
        
        dx = []
        for i in range(len(plus_di)):
            if plus_di[i] is not None and minus_di[i] is not None:
                di_sum = plus_di[i] + minus_di[i]
                if di_sum > 0:
                    dx_val = abs(plus_di[i] - minus_di[i]) / di_sum * 100
                else:
                    dx_val = 0
                dx.append(dx_val)
            else:
                dx.append(None)
        
        # ADX is SMA of DX
        for i in range(len(dx)):
            if i < period - 1 or dx[i] is None:
                continue
            
            if i == period - 1:
                # First ADX is SMA
                valid_dx = [v for v in dx[i - period + 1:i + 1] if v is not None]
                if valid_dx:
                    adx[i] = sum(valid_dx) / len(valid_dx)
            else:
                # Subsequent ADX uses smoothing
                if adx[i - 1] is not None and dx[i] is not None:
                    adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
        
        return adx
    
    @staticmethod
    def get_trend_strength(adx_value: Optional[float]) -> str:
        """
        Classify trend strength
        
        Args:
            adx_value: ADX value
        
        Returns:
            'STRONG' (>25), 'MODERATE' (20-25), 'WEAK' (<20), or 'INVALID'
        """
        if adx_value is None:
            return 'INVALID'
        elif adx_value > 25:
            return 'STRONG'
        elif adx_value >= 20:
            return 'MODERATE'
        else:
            return 'WEAK'


def main():
    """Run a standalone ADX demo."""
    from trading_system.utils.standalone import print_json, sample_price_lists

    high, low, close = sample_price_lists()
    values = ADXIndicator.calculate(high, low, close, period=14)
    latest = values[-1]

    print_json(
        {
            "latest_adx": latest,
            "trend_strength": ADXIndicator.get_trend_strength(latest),
            "computed_points": len([value for value in values if value is not None]),
        }
    )


if __name__ == "__main__":
    main()
