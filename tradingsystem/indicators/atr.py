"""
ATR Indicator (Average True Range)
Measures market volatility.
Used for:
- Stop loss placement (typically 1.5x or 2x ATR from entry)
- Target placement (typically 3x ATR from entry)
- Position sizing (risk = N% of account / ATR)
"""

from typing import List, Optional
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(next(parent for parent in Path(__file__).resolve().parents if (parent / "tradingsystem").exists())))


class ATRIndicator:
    """Calculate Average True Range"""
    
    @staticmethod
    def calculate(
        high: List[float],
        low: List[float],
        close: List[float],
        period: int = 14
    ) -> List[Optional[float]]:
        """
        Calculate ATR
        
        Args:
            high: High prices
            low: Low prices
            close: Close prices
            period: ATR period (default 14)
        
        Returns:
            List of ATR values (first period-1 are None)
        """
        if len(high) < period or len(low) < period or len(close) < period:
            return [None] * len(close)
        
        # Calculate True Range
        tr = ATRIndicator._calculate_tr(high, low, close)
        
        # Calculate ATR (EMA of TR)
        atr = [None] * (period - 1)
        
        # First ATR is SMA
        atr_val = sum(tr[:period]) / period
        atr.append(atr_val)
        
        # Subsequent ATR uses EMA smoothing
        multiplier = 2 / (period + 1)
        for i in range(period + 1, len(tr)):
            atr_val = atr[-1] * (1 - multiplier) + tr[i] * multiplier
            atr.append(atr_val)
        
        return atr
    
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
    def get_stop_loss(entry_price: float, side: str, atr: float, multiplier: float = 1.5) -> float:
        """
        Calculate stop loss using ATR
        
        Args:
            entry_price: Entry price
            side: 'BUY' or 'SELL'
            atr: ATR value
            multiplier: Number of ATRs for stop loss (default 1.5)
        
        Returns:
            Stop loss price
        """
        if side == "BUY":
            return entry_price - (atr * multiplier)
        else:  # SELL
            return entry_price + (atr * multiplier)
    
    @staticmethod
    def get_target(entry_price: float, side: str, atr: float, multiplier: float = 3.0) -> float:
        """
        Calculate target using ATR
        
        Args:
            entry_price: Entry price
            side: 'BUY' or 'SELL'
            atr: ATR value
            multiplier: Number of ATRs for target (default 3.0)
        
        Returns:
            Target price
        """
        if side == "BUY":
            return entry_price + (atr * multiplier)
        else:  # SELL
            return entry_price - (atr * multiplier)
    
    @staticmethod
    def get_risk_reward_ratio(entry: float, stop_loss: float, target: float, side: str) -> float:
        """
        Calculate risk-reward ratio
        
        Args:
            entry: Entry price
            stop_loss: Stop loss price
            target: Target price
            side: 'BUY' or 'SELL'
        
        Returns:
            Risk-reward ratio (e.g., 2.0 means 1:2 reward:risk)
        """
        risk = abs(entry - stop_loss)
        reward = abs(target - entry)
        
        if risk == 0:
            return 0.0
        
        return reward / risk


def main():
    """Run a standalone ATR demo."""
    from trading_system.utils.standalone import print_json, sample_price_lists

    high, low, close = sample_price_lists()
    values = ATRIndicator.calculate(high, low, close, period=14)
    latest = values[-1]
    entry_price = close[-1]
    stop_loss = ATRIndicator.get_stop_loss(entry_price, "BUY", latest or 0.0, multiplier=1.5)
    target = ATRIndicator.get_target(entry_price, "BUY", latest or 0.0, multiplier=3.0)

    print_json(
        {
            "latest_atr": latest,
            "stop_loss": stop_loss,
            "target": target,
            "risk_reward_ratio": ATRIndicator.get_risk_reward_ratio(entry_price, stop_loss, target, "BUY"),
        }
    )


if __name__ == "__main__":
    main()
