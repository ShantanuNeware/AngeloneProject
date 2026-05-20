"""Lightweight indicators ported from 07_Jan_2026/indicators.py

Includes:
- hull_moving_average
- mcginley
- zlema
- calculate_slope_and_angle
- rsi_indicator
- detect_divergences
- keltner_channels (basic)

These implementations avoid external `ta` dependency where possible.
"""

import pandas as pd
import numpy as np
from typing import Optional


def hull_moving_average(series: pd.Series, period: int = 14) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce").fillna(0)
    half_length = int(period / 2)
    sqrt_length = int(np.sqrt(period)) if period > 0 else 1
    wma_half = series.rolling(window=half_length, min_periods=1).mean()
    wma_full = series.rolling(window=period, min_periods=1).mean()
    hull_raw = 2 * wma_half - wma_full
    return hull_raw.rolling(window=max(1, sqrt_length), min_periods=1).mean()


def mcginley(series: pd.Series, period: int = 14) -> pd.Series:
    mcg = np.zeros_like(series, dtype=np.float64)
    if len(series) == 0:
        return pd.Series(mcg, index=series.index)
    mcg[0] = series.iloc[0]

    k = 0.6
    for i in range(1, len(series)):
        prev = mcg[i-1]
        price = series.iloc[i]
        if prev == 0:
            mcg[i] = price
            continue
        denominator = period * ((price / prev) ** 4) if prev != 0 else period
        denominator = max(denominator, 1e-8)
        change = (price - prev) / denominator
        change = np.clip(change, -100, 100)
        mcg[i] = prev + change

    return pd.Series(mcg, index=series.index)


def zlema(series: pd.Series, period: int = 14) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce").fillna(0)
    lag = (period - 1) // 2
    ema_input = series + (series - series.shift(lag))
    return ema_input.ewm(span=period, adjust=False).mean()


def calculate_slope_and_angle(series: pd.Series, period: int = 5) -> pd.DataFrame:
    series = pd.to_numeric(series, errors="coerce")

    n = period
    if n <= 1:
        slope = pd.Series(np.zeros(len(series)), index=series.index)
        angle = pd.Series(np.zeros(len(series)), index=series.index)
        return pd.DataFrame({"Slope": slope, "Angle": angle, "Trend": np.zeros(len(series)), "SlopeFlip": np.zeros(len(series)), "LongSignal": np.zeros(len(series)), "ShortSignal": np.zeros(len(series))}, index=series.index)

    x = np.arange(n)
    x_mean = x.mean()
    x_demeaned = x - x_mean
    denom = np.sum(x_demeaned ** 2)

    y = series.values
    slopes = np.full(len(y), np.nan)

    for i in range(n - 1, len(y)):
        y_window = y[i - n + 1: i + 1]
        if np.any(np.isnan(y_window)):
            continue
        y_mean = y_window.mean()
        slopes[i] = np.sum(x_demeaned * (y_window - y_mean)) / denom

    slope = pd.Series(slopes, index=series.index)
    angle = np.degrees(np.arctan(slope))

    trend = np.where(slope > 0, 1, np.where(slope < 0, -1, 0))
    trend = pd.Series(trend, index=series.index)
    slope_flip = (slope * slope.shift(1) < 0)

    long_signal = (slope > 0) & (slope.shift(1) <= 0)
    short_signal = (slope < 0) & (slope.shift(1) >= 0)

    return pd.DataFrame({
        "Slope": slope,
        "Angle": angle,
        "Trend": trend,
        "SlopeFlip": slope_flip,
        "LongSignal": long_signal,
        "ShortSignal": short_signal,
    }, index=series.index)


def rsi_indicator(df: pd.DataFrame, length: int = 7, source: str = "Close") -> pd.Series:
    src = pd.to_numeric(df[source], errors="coerce")
    delta = src.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    roll_up = gain.ewm(alpha=1 / length, adjust=False).mean()
    roll_down = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100 / (1 + rs))


def detect_divergences(df: pd.DataFrame, rsi_values: pd.Series, pivot_lookback_left: int = 7, pivot_lookback_right: int = 2, max_lookback_bars: int = 60):
    if df is None or df.empty or rsi_values is None or rsi_values.empty:
        return pd.Series(0, index=df.index), pd.Series(0, index=df.index)

    bull_div = pd.Series(0, index=df.index)
    bear_div = pd.Series(0, index=df.index)

    highs = df["High"].values
    lows = df["Low"].values
    rsi = rsi_values.values
    n = len(df)

    rsi_pivot_lows = []
    rsi_pivot_highs = []

    start_idx = pivot_lookback_left
    end_idx = n - pivot_lookback_right

    for i in range(start_idx, end_idx):
        curr_rsi = rsi[i]
        is_pivot_low = True
        for k in range(1, pivot_lookback_left + 1):
            if rsi[i - k] <= curr_rsi:
                is_pivot_low = False
                break
        if is_pivot_low:
            for k in range(1, pivot_lookback_right + 1):
                if rsi[i + k] <= curr_rsi:
                    is_pivot_low = False
                    break
        if is_pivot_low:
            curr_idx = i
            curr_price_low = lows[i]
            signal_idx = i + pivot_lookback_right
            if rsi_pivot_lows:
                for prev in reversed(rsi_pivot_lows):
                    prev_idx = prev['idx']
                    prev_rsi = prev['rsi']
                    prev_price = prev['price']
                    if (curr_idx - prev_idx) > max_lookback_bars:
                        break
                    if curr_rsi > prev_rsi and curr_price_low < prev_price:
                        bull_div.iloc[signal_idx] = 1
                        break
            rsi_pivot_lows.append({'idx': curr_idx, 'price': curr_price_low, 'rsi': curr_rsi})
            if len(rsi_pivot_lows) > 0:
                first_idx = rsi_pivot_lows[0]['idx']
                if (curr_idx - first_idx) > (max_lookback_bars * 5):
                    rsi_pivot_lows.pop(0)

        is_pivot_high = True
        for k in range(1, pivot_lookback_left + 1):
            if rsi[i - k] >= curr_rsi:
                is_pivot_high = False
                break
        if is_pivot_high:
            for k in range(1, pivot_lookback_right + 1):
                if rsi[i + k] >= curr_rsi:
                    is_pivot_high = False
                    break
        if is_pivot_high:
            curr_idx = i
            curr_price_high = highs[i]
            signal_idx = i + pivot_lookback_right
            if rsi_pivot_highs:
                for prev in reversed(rsi_pivot_highs):
                    prev_idx = prev['idx']
                    prev_rsi = prev['rsi']
                    prev_price = prev['price']
                    if (curr_idx - prev_idx) > max_lookback_bars:
                        break
                    if curr_rsi < prev_rsi and curr_price_high > prev_price:
                        bear_div.iloc[signal_idx] = 1
                        break
            rsi_pivot_highs.append({'idx': curr_idx, 'price': curr_price_high, 'rsi': curr_rsi})
            if len(rsi_pivot_highs) > 0:
                first_idx = rsi_pivot_highs[0]['idx']
                if (curr_idx - first_idx) > (max_lookback_bars * 5):
                    rsi_pivot_highs.pop(0)

    return bull_div, bear_div


def keltner_channels(df: pd.DataFrame, length: int = 20, mult: float = 2.0, source: str = "Close", use_exp: bool = True, bands_style: str = "Average True Range", atr_length: int = 10) -> pd.DataFrame:
    df = df.copy()
    src = pd.to_numeric(df[source], errors="coerce").fillna(0)
    high = pd.to_numeric(df["High"], errors="coerce").fillna(0)
    low = pd.to_numeric(df["Low"], errors="coerce").fillna(0)
    close = pd.to_numeric(df["Close"], errors="coerce").fillna(0)

    if use_exp:
        ma = src.ewm(span=length, adjust=False).mean()
    else:
        ma = src.rolling(window=length).mean()

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    if bands_style == "True Range":
        rangema = tr
    elif bands_style == "Average True Range":
        rangema = tr.ewm(alpha=1/atr_length, adjust=False).mean()
    elif bands_style == "Range":
        hl_diff = high - low
        rangema = hl_diff.ewm(alpha=1/length, adjust=False).mean()
    else:
        rangema = tr.ewm(alpha=1/atr_length, adjust=False).mean()

    upper = ma + rangema * mult
    lower = ma - rangema * mult

    df["KC_Basis"] = ma
    df["KC_Upper"] = upper
    df["KC_Lower"] = lower
    return df
