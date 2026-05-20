# fibonacci_levels.py - Fibonacci Support/Resistance Calculator
"""
Calculate Fibonacci retracement and extension levels from price data.

Fibonacci Retracement Levels:
- 23.6%, 38.2%, 50.0%, 61.8%, 78.6%

Fibonacci Extension Levels:
- 127.2%, 141.4%, 161.8%, 200.0%, 261.8%
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# ATR CALCULATION (Used for swing filtering)
# ---------------------------------------------------------
def _calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if df is None or len(df) < period + 2:
        return pd.Series([0] * len(df))

    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().fillna(0)
    return atr


# ---------------------------------------------------------
# ATR-FILTERED PIVOT CHECKS (Used directly in swing detection)
# ---------------------------------------------------------
def _atr_pivot_high(df: pd.DataFrame, idx: int, atr: float, strength: int = 3) -> bool:
    """Pivot High must exceed surrounding candles by ATR * factor."""
    if idx < strength or idx + strength >= len(df):
        return False
    center_high = df["High"].iloc[idx]
    left = df["High"].iloc[idx - strength:idx]
    right = df["High"].iloc[idx + 1:idx + 1 + strength]
    return center_high > left.max() + atr and center_high > right.max() + atr


def _atr_pivot_low(df: pd.DataFrame, idx: int, atr: float, strength: int = 3) -> bool:
    """Pivot Low must be lower than surrounding candles by ATR * factor."""
    if idx < strength or idx + strength >= len(df):
        return False
    center_low = df["Low"].iloc[idx]
    left = df["Low"].iloc[idx - strength:idx]
    right = df["Low"].iloc[idx + 1:idx + 1 + strength]
    return center_low < left.min() - atr and center_low < right.min() - atr


# ---------------------------------------------------------
# (Legacy) Original signature pivot detectors - UNTOUCHED
# These remain for compatibility, but internal detection
# now uses ATR-enhanced pivot logic.
# ---------------------------------------------------------
def _is_pivot_high(df, i):
    if i < 2 or i > len(df) - 3:
        return False
    return df["High"].iloc[i] > df["High"].iloc[i - 1] and df["High"].iloc[i] > df["High"].iloc[i + 1]


def _is_pivot_low(df, i):
    if i < 2 or i > len(df) - 3:
        return False
    return df["Low"].iloc[i] < df["Low"].iloc[i - 1] and df["Low"].iloc[i] < df["Low"].iloc[i + 1]


# ---------------------------------------------------------
# SWING DETECTION (ATR-robust)
# ---------------------------------------------------------
def find_swing_points(
    df: pd.DataFrame,
    lookback: int = 20,
    atr_period: int = 14
) -> Tuple[Optional[float], Optional[float], Optional[int], Optional[int]]:
    """
    Detect swing high/low using ATR-filtered pivots.
    Function signature is unchanged.
    """

    if df is None or len(df) < lookback:
        return None, None, None, None

    recent_df = df.tail(lookback).copy()
    atr_series = _calculate_atr(recent_df, atr_period)

    pivot_highs = []
    pivot_lows = []

    for i in range(len(recent_df)):
        if _atr_pivot_high(recent_df, i, atr_series.iloc[i]):
            pivot_highs.append(i)
        if _atr_pivot_low(recent_df, i, atr_series.iloc[i]):
            pivot_lows.append(i)

    # Primary (ATR pivots)
    if pivot_highs:
        high_idx = pivot_highs[-1]
        swing_high = recent_df["High"].iloc[high_idx]
        high_idx_original = recent_df.index[high_idx]
    else:
        # Fallback → peak filtered by ATR
        high_idx_label = recent_df["High"].idxmax()
        swing_high = recent_df["High"].max()
        # Convert label to position within recent_df
        high_idx_original = high_idx_label

    if pivot_lows:
        low_idx = pivot_lows[-1]
        swing_low = recent_df["Low"].iloc[low_idx]
        low_idx_original = recent_df.index[low_idx]
    else:
        # Fallback → trough filtered by ATR
        low_idx_label = recent_df["Low"].idxmin()
        swing_low = recent_df["Low"].min()
        # Convert label to position within recent_df
        low_idx_original = low_idx_label

    return (
        float(swing_high),
        float(swing_low),
        int(high_idx_original),
        int(low_idx_original),
    )


# ---------------------------------------------------------
# RETRACEMENTS
# ---------------------------------------------------------
def calculate_fibonacci_retracement(high: float, low: float, trend: str = "uptrend") -> Dict[str, float]:
    diff = high - low
    if trend == "uptrend":
        return {
            "fib_0": round(high, 2),
            "fib_23.6": round(high - diff * 0.236, 2),
            "fib_38.2": round(high - diff * 0.382, 2),
            "fib_50.0": round(high - diff * 0.500, 2),
            "fib_61.8": round(high - diff * 0.618, 2),
            "fib_78.6": round(high - diff * 0.786, 2),
            "fib_100": round(low, 2),
        }
    else:
        return {
            "fib_0": round(low, 2),
            "fib_23.6": round(low + diff * 0.236, 2),
            "fib_38.2": round(low + diff * 0.382, 2),
            "fib_50.0": round(low + diff * 0.500, 2),
            "fib_61.8": round(low + diff * 0.618, 2),
            "fib_78.6": round(low + diff * 0.786, 2),
            "fib_100": round(high, 2),
        }


# ---------------------------------------------------------
# EXTENSIONS
# ---------------------------------------------------------
def calculate_fibonacci_extension(high: float, low: float, trend: str = "uptrend") -> Dict[str, float]:
    diff = high - low
    if trend == "uptrend":
        return {
            "ext_127.2": round(high + diff * 0.272, 2),
            "ext_141.4": round(high + diff * 0.414, 2),
            "ext_161.8": round(high + diff * 0.618, 2),
            "ext_200.0": round(high + diff, 2),
            "ext_261.8": round(high + diff * 1.618, 2),
        }
    else:
        return {
            "ext_127.2": round(low - diff * 0.272, 2),
            "ext_141.4": round(low - diff * 0.414, 2),
            "ext_161.8": round(low - diff * 0.618, 2),
            "ext_200.0": round(low - diff, 2),
            "ext_261.8": round(low - diff * 1.618, 2),
        }


# ---------------------------------------------------------
# MASTER WRAPPER – SAME SIGNATURE
# ---------------------------------------------------------
def get_fibonacci_levels(
    df: pd.DataFrame,
    lookback: int = 20,
    auto_trend: bool = True,
    atr_period: int = 14
) -> Optional[Dict]:

    if df is None or len(df) < lookback:
        logger.warning("Insufficient data for Fibonacci calculation")
        return None

    swing_high, swing_low, high_idx, low_idx = find_swing_points(df, lookback, atr_period)

    if swing_high is None or swing_low is None:
        return None

    current_price = float(df["Close"].iloc[-1])

    # Trend logic unchanged
    if auto_trend:
        trend = "uptrend" if high_idx < low_idx else "downtrend"
    else:
        midpoint = (swing_high + swing_low) / 2
        trend = "uptrend" if current_price > midpoint else "downtrend"

    retracement = calculate_fibonacci_retracement(swing_high, swing_low, trend)
    extension = calculate_fibonacci_extension(swing_high, swing_low, trend)

    if trend == "uptrend":
        support = [v for v in retracement.values() if v < current_price]
        resistance = [v for v in list(retracement.values()) + list(extension.values()) if v > current_price]
    else:
        resistance = [v for v in retracement.values() if v > current_price]
        support = [v for v in list(retracement.values()) + list(extension.values()) if v < current_price]

    nearest_support = max(support) if support else swing_low
    nearest_resistance = min(resistance) if resistance else swing_high

    return {
        "trend": trend,
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "current_price": round(current_price, 2),
        "price_range": round(swing_high - swing_low, 2),
        "retracement": retracement,
        "extension": extension,
        "nearest_support": round(nearest_support, 2),
        "nearest_resistance": round(nearest_resistance, 2),
        "distance_to_support": round(current_price - nearest_support, 2),
        "distance_to_resistance": round(nearest_resistance - current_price, 2),
    }


# ---------------------------------------------------------
# SIGNALS (same API)
# ---------------------------------------------------------
def get_fibonacci_signal(fib_data: Dict, current_price: float) -> Optional[str]:

    if not fib_data:
        return None

    trend = fib_data["trend"]
    retr = fib_data["retracement"]
    ns = fib_data["nearest_support"]
    nr = fib_data["nearest_resistance"]

    sd = abs(current_price - ns) / current_price * 100
    rd = abs(current_price - nr) / current_price * 100

    if trend == "uptrend" and sd < 0.2:
        if abs(current_price - retr["fib_61.8"]) / current_price * 100 < 0.3:
            return "CALL (at 61.8% Fib support - Golden Ratio)"
        if abs(current_price - retr["fib_50.0"]) / current_price * 100 < 0.3:
            return "CALL (at 50% Fib support)"

    if trend == "downtrend" and rd < 0.2:
        if abs(current_price - retr["fib_61.8"]) / current_price * 100 < 0.3:
            return "PUT (at 61.8% Fib resistance - Golden Ratio)"
        if abs(current_price - retr["fib_50.0"]) / current_price * 100 < 0.3:
            return "PUT (at 50% Fib resistance)"

    return None



def main():
    """Test Fibonacci calculator with dummy data"""
    print("Testing Fibonacci Level Calculator...\n")

    # Create dummy price data (simulating an uptrend with pullback)
    dummy_df = pd.DataFrame({
        'DateTime': pd.date_range(end=pd.Timestamp.now(), periods=30, freq='1min'),
        'Open': [25000, 25020, 25040, 25060, 25080, 25100, 25120, 25140, 25160, 25180,
                 25200, 25220, 25240, 25260, 25280, 25300, 25290, 25280, 25270, 25260,
                 25250, 25240, 25230, 25220, 25210, 25200, 25190, 25180, 25170, 25160],
        'High': [25025, 25045, 25065, 25085, 25105, 25125, 25145, 25165, 25185, 25205,
                 25225, 25245, 25265, 25285, 25305, 25320, 25305, 25295, 25285, 25275,
                 25265, 25255, 25245, 25235, 25225, 25215, 25205, 25195, 25185, 25175],
        'Low': [24995, 25015, 25035, 25055, 25075, 25095, 25115, 25135, 25155, 25175,
                25195, 25215, 25235, 25255, 25275, 25285, 25275, 25265, 25255, 25245,
                25235, 25225, 25215, 25205, 25195, 25185, 25175, 25165, 25155, 25145],
        'Close': [25020, 25040, 25060, 25080, 25100, 25120, 25140, 25160, 25180, 25200,
                  25220, 25240, 25260, 25280, 25300, 25290, 25280, 25270, 25260, 25250,
                  25240, 25230, 25220, 25210, 25200, 25190, 25180, 25170, 25160, 25150],
    })

    # Calculate Fibonacci levels
    fib_data = get_fibonacci_levels(dummy_df, lookback=30)

    if fib_data:
        print(f"📊 Fibonacci Analysis")
        print(f"{'='*60}")
        print(f"Trend: {fib_data['trend'].upper()}")
        print(f"Swing High: {fib_data['swing_high']}")
        print(f"Swing Low: {fib_data['swing_low']}")
        print(f"Current Price: {fib_data['current_price']}")
        print(f"Price Range: {fib_data['price_range']}")

        print(f"\n🔻 Retracement Levels (Support in Uptrend):")
        for level, price in fib_data['retracement'].items():
            marker = "👉" if abs(price - fib_data['current_price']) < 10 else "  "
            print(f"{marker} {level:12s}: {price:8.2f}")

        print(f"\n🔺 Extension Levels (Targets):")
        for level, price in fib_data['extension'].items():
            print(f"   {level:12s}: {price:8.2f}")

        print(f"\n📍 Key Levels:")
        print(f"   Nearest Support: {fib_data['nearest_support']} (distance: {fib_data['distance_to_support']:.2f})")
        print(f"   Nearest Resistance: {fib_data['nearest_resistance']} (distance: {fib_data['distance_to_resistance']:.2f})")

        # Get trading signal
        signal = get_fibonacci_signal(fib_data, fib_data['current_price'])
        if signal:
            print(f"\n✅ Signal: {signal}")
        else:
            print(f"\n❌ No Fibonacci signal at current price")
    else:
        print("❌ Failed to calculate Fibonacci levels")


if __name__ == "__main__":
    main()
