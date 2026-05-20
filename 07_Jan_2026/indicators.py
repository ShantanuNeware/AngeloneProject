import logging
import pandas as pd
import numpy as np
import ta
import indicators_config as cfg
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# ✅ HULL MOVING AVERAGE
# ============================================================


def hull_moving_average(series: pd.Series, period: int = cfg.HMA_PERIOD) -> pd.Series:
    """Compute the Hull Moving Average (HMA)."""
    series = pd.to_numeric(series, errors="coerce").fillna(0)
    half_length = int(period / 2)
    sqrt_length = int(np.sqrt(period))
    wma_half = series.rolling(window=half_length, min_periods=1).mean()
    wma_full = series.rolling(window=period, min_periods=1).mean()
    hull_raw = 2 * wma_half - wma_full
    return hull_raw.rolling(window=sqrt_length, min_periods=1).mean()


def warmup_hull_with_historical(
    df: pd.DataFrame, period: int = cfg.HMA_PERIOD, candles: int = cfg.HMA_WARMUP_CANDLES
) -> float:
    """Warm up Hull MA using last N historical closes."""
    closes = pd.to_numeric(df["Close"], errors="coerce").dropna().tail(candles)
    if closes.empty:
        return None
    hma = hull_moving_average(closes, period).iloc[-1]
    logger.info(f"HMA warm-up complete → {hma:.2f}")
    return hma


# ============================================================
# ✅ MCGINLEY DYNAMIC
# ============================================================


def mcginley(series: pd.Series, period: int = cfg.MCGINLEY_PERIOD) -> pd.Series:
    mcg = np.zeros_like(series, dtype=np.float32)
    mcg[0] = series.iloc[0]
    
    for i in range(1, len(series)):
        # Prevent division by very small numbers
        denominator = period * pow(series.iloc[i]/mcg[i-1], 4) if mcg[i-1] != 0 else period
        denominator = max(denominator, 1e-8)  # Ensure minimum denominator value
        
        # Calculate change with bounds checking
        change = (series.iloc[i] - mcg[i-1]) / denominator
        change = np.clip(change, -100, 100)  # Limit extreme changes
        
        mcg[i] = mcg[i-1] + change
        
    return pd.Series(mcg, index=series.index)


def warmup_mcginley_with_historical(
    df: pd.DataFrame, period: int = cfg.MCGINLEY_WARMUP_PERIOD, candles: int = cfg.MCGINLEY_WARMUP_CANDLES
) -> float:
    """Initialize McGinley with last N historical closes."""
    closes = pd.to_numeric(df["Close"], errors="coerce").dropna().tail(candles)
    if closes.empty:
        return None
    mcg_val = closes.iloc[0]
    k = cfg.MCGINLEY_K
    for price in closes.iloc[1:]:
        ratio = (price / mcg_val) if mcg_val != 0 else 1
        mcg_val += (price - mcg_val) / (k * period * (ratio**4))
    logger.info(f"McGinley warm-up complete → {mcg_val:.2f}")
    return mcg_val


# ============================================================
# ✅ TREND MAGIC
# ============================================================


def trend_magic(df: pd.DataFrame, atr_period: int = cfg.TREND_MAGIC_ATR_PERIOD) -> pd.DataFrame:
    """ATR-based Trend Magic indicator."""
    high = pd.to_numeric(df["High"], errors="coerce").fillna(0)
    low = pd.to_numeric(df["Low"], errors="coerce").fillna(0)
    close = pd.to_numeric(df["Close"], errors="coerce").fillna(0)

    tr = pd.concat(
        [(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(window=atr_period, min_periods=1).mean()
    magic_trend = pd.Series(index=close.index, dtype=float)
    direction = pd.Series(index=close.index, dtype=int)

    for i in range(len(close)):
        if i == 0:
            magic_trend.iloc[i] = close.iloc[i]
            direction.iloc[i] = 1
        else:
            prev_trend = magic_trend.iloc[i - 1]
            if close.iloc[i] > prev_trend:
                magic_trend.iloc[i] = max(prev_trend, low.iloc[i] - atr.iloc[i])
                direction.iloc[i] = 1
            elif close.iloc[i] < prev_trend:
                magic_trend.iloc[i] = min(prev_trend, high.iloc[i] + atr.iloc[i])
                direction.iloc[i] = -1
            else:
                magic_trend.iloc[i] = prev_trend
                direction.iloc[i] = direction.iloc[i - 1]

    flat_market = atr < (atr.mean() * 0.5)
    return pd.DataFrame(
        {"MagicTrend": magic_trend, "Direction": direction, "flat_market": flat_market}
    )


def compute_trend_magic(high, low, close, period=10):
    """Quick Trend Magic without full DataFrame."""
    return trend_magic(
        pd.DataFrame({"High": high, "Low": low, "Close": close}), atr_period=period
    )


# ============================================================
# ✅ ZLEMA (Zero-Lag EMA)
# ============================================================


def zlema(series: pd.Series, period: int = cfg.ZLEMA_PERIOD) -> pd.Series:
    """Zero-Lag Exponential Moving Average."""
    series = pd.to_numeric(series, errors="coerce").fillna(0)
    lag = (period - 1) // 2
    ema_input = series + (series - series.shift(lag))
    return ema_input.ewm(span=period, adjust=False).mean()


def warmup_zlema_with_historical(
    df: pd.DataFrame, period: int = cfg.ZLEMA_WARMUP_PERIOD, candles: int = cfg.ZLEMA_WARMUP_CANDLES
) -> float:
    """Initialize ZLEMA using last N closes."""
    closes = pd.to_numeric(df["Close"], errors="coerce").dropna().tail(candles)
    if closes.empty:
        return None
    z_val = zlema(closes, period).iloc[-1]
    logger.info(f"ZLEMA warm-up complete → {z_val:.2f}")
    return z_val


# ============================================================
# ✅ UT BOT ALERTS
# ============================================================


def ut_bot_signals(df, a, c, use_heikin=False):
    """UT Bot Alerts - ATR-based trailing stop system."""
    df = df.copy()
    if use_heikin:
        ha_df = df.copy()
        ha_df["Close"] = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
        ha_open = np.zeros(len(df))
        ha_open[0] = (df["Open"].iloc[0] + df["Close"].iloc[0]) / 2
        for i in range(1, len(df)):
            ha_open[i] = (ha_open[i - 1] + ha_df["Close"].iloc[i - 1]) / 2
        ha_df["Open"] = ha_open
        ha_df["High"] = ha_df[["Open", "Close", "High"]].max(axis=1)
        ha_df["Low"] = ha_df[["Open", "Close", "Low"]].min(axis=1)
        src = ha_df["Close"].values
    else:
        src = df["Close"].values

    atr = (
        ta.volatility.AverageTrueRange(
            high=df["High"], low=df["Low"], close=df["Close"], window=c
        )
        .average_true_range()
        .values
    )

    nLoss = a * atr
    xATRTrailingStop = np.zeros(len(df))
    pos = np.zeros(len(df))
    xATRTrailingStop[0] = src[0] - nLoss[0]

    for i in range(1, len(df)):
        prev_stop = xATRTrailingStop[i - 1]
        if src[i] > prev_stop and src[i - 1] > prev_stop:
            xATRTrailingStop[i] = max(prev_stop, src[i] - nLoss[i])
        elif src[i] < prev_stop and src[i - 1] < prev_stop:
            xATRTrailingStop[i] = min(prev_stop, src[i] + nLoss[i])
        else:
            xATRTrailingStop[i] = (
                src[i] - nLoss[i] if src[i] > prev_stop else src[i] + nLoss[i]
            )
        pos[i] = (
            1
            if src[i - 1] < prev_stop and src[i] > prev_stop
            else -1 if src[i - 1] > prev_stop and src[i] < prev_stop else pos[i - 1]
        )

    df["UT_TrailingStop"] = xATRTrailingStop
    df["Signal"] = np.where(pos == 1, "BUY", np.where(pos == -1, "SELL", None))
    df["Position"] = pos
    return df


# ============================================================
# ✅ BOLLINGER BANDS
# ============================================================


def bollinger_bands(df, length=cfg.BB_LENGTH, mult=cfg.BB_MULT, ma_type=cfg.BB_MA_TYPE, offset=cfg.BB_OFFSET):
    """Compute Bollinger Bands."""
    df = df.copy()
    src = df.astype(float)

    if ma_type == "SMA":
        basis = src.rolling(window=length).mean()
    elif ma_type == "EMA":
        basis = src.ewm(span=length, adjust=False).mean()
    else:
        raise ValueError(f"Unsupported MA type: {ma_type}")

    dev = src.rolling(window=length).std(ddof=0) * mult
    upper = basis + dev
    lower = basis - dev

    if offset != 0:
        basis, upper, lower = (
            basis.shift(offset),
            upper.shift(offset),
            lower.shift(offset),
        )

    df["BB_Basis"] = basis
    df["BB_Upper"] = upper
    df["BB_Lower"] = lower
    return df


# ============================================================
# ✅ RSI & DIVERGENCES
# ============================================================


def rsi_indicator(
    df: pd.DataFrame, length: int = cfg.RSI_LENGTH, source: str = cfg.RSI_SOURCE
) -> pd.Series:
    """Compute Relative Strength Index (RSI)."""
    src = pd.to_numeric(df[source], errors="coerce")
    delta = src.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    roll_up = gain.ewm(alpha=1 / length, adjust=False).mean()
    roll_down = loss.ewm(alpha=1 / length, adjust=False).mean()
    # Add a small epsilon to prevent division by zero
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100 / (1 + rs))


def rsi_ma(
    df: pd.DataFrame, rsi_values: pd.Series, ma_type: str = cfg.RSI_MA_TYPE, length: int = cfg.RSI_MA_LENGTH
) -> pd.Series:
    """Smooth RSI with moving average."""
    if ma_type == "SMA":
        return rsi_values.rolling(window=length).mean()
    elif ma_type == "EMA":
        return rsi_values.ewm(span=length, adjust=False).mean()
    else:
        return rsi_values


def detect_divergences(
    df: pd.DataFrame,
    rsi_values: pd.Series,
    pivot_lookback_left: int = cfg.DIVERGENCE_PIVOT_LOOKBACK_LEFT,
    pivot_lookback_right: int = cfg.DIVERGENCE_PIVOT_LOOKBACK_RIGHT,
    max_lookback_bars: int = cfg.DIVERGENCE_MAX_LOOKBACK_BARS,
):
    """
    Detect bullish and bearish divergences using Pivot Points on RSI (Pine Script logic).
    
    Logic Update (Match Pine Script):
    - Pivots are detected on the RSI indicator itself, not on Price.
    - BULLISH Divergence:
        - Found RSI Pivot Low (valley).
        - Compare with previous RSI Pivot Lows within lookback.
        - Condition: Current RSI Low > Previous RSI Low (Higher Low on RSI).
        - Condition: Current Price Low < Previous Price Low (Lower Low on Price).
    - BEARISH Divergence:
        - Found RSI Pivot High (peak).
        - Compare with previous RSI Pivot Highs within lookback.
        - Condition: Current RSI High < Previous RSI High (Lower High on RSI).
        - Condition: Current Price High > Previous Price High (Higher High on Price).
    
    :param df: DataFrame with High, Low columns
    :param rsi_values: RSI Series
    :param pivot_lookback_left: Bars to the left to confirm pivot
    :param pivot_lookback_right: Bars to the right to confirm pivot
    :param max_lookback_bars: Max distance between pivots
    :return: (bull_div_series, bear_div_series)
    """
    if df is None or df.empty or rsi_values is None or rsi_values.empty:
        return pd.Series(0, index=df.index), pd.Series(0, index=df.index)

    # Prepare output series
    bull_div = pd.Series(0, index=df.index)
    bear_div = pd.Series(0, index=df.index)
    
    # We need to access values by integer index for speed and lookbacks
    highs = df["High"].values
    lows = df["Low"].values
    rsi = rsi_values.values
    n = len(df)
    
    # Store detected pivots: (index, price_at_pivot, rsi_at_pivot)
    # We use lists to simulate the dynamic arrays in Pine Script
    rsi_pivot_lows = []   # Format: {'idx': int, 'price': float, 'rsi': float}
    rsi_pivot_highs = []  # Format: {'idx': int, 'price': float, 'rsi': float}
    
    # We can rely on 'ta' library for pivot detection logic or implement manually to match Pine's simple scan.
    # Implementing manual loop to strictly follow "left/right" lookback logic on RSI.
    
    # Start iterating where we have enough data for left lookback
    # And stop where we have enough for right lookback
    start_idx = pivot_lookback_left
    end_idx = n - pivot_lookback_right
    
    for i in range(start_idx, end_idx):
        # -------------------------------
        # 1. DETECT RSI PIVOT LOW (Valley)
        # -------------------------------
        # Pivot is at 'i'. Check neighbors.
        curr_rsi = rsi[i]
        
        is_pivot_low = True
        
        # Check Left
        for k in range(1, pivot_lookback_left + 1):
            if rsi[i - k] <= curr_rsi: # If neighbor is lower or equal, 'i' is not a strict low
                is_pivot_low = False
                break
                
        # Check Right
        if is_pivot_low:
            for k in range(1, pivot_lookback_right + 1):
                if rsi[i + k] <= curr_rsi:
                    is_pivot_low = False
                    break
        
        if is_pivot_low:
            # Current Pivot Details
            curr_idx = i
            curr_price_low = lows[i] # Price at the moment of RSI valley
            
            # Use specific Pivot Lookback Right offset for signal placement if we want to match exact bar
            # Usually signal appears when pivot is confirmed (i + pivot_lookback_right)
            signal_idx = i + pivot_lookback_right
            
            # Check against history
            if rsi_pivot_lows:
                # Iterate backwards to find a valid divergence
                for prev in reversed(rsi_pivot_lows):
                    prev_idx = prev['idx']
                    prev_rsi = prev['rsi']
                    prev_price = prev['price']
                    
                    # Check Max Lookback
                    if (curr_idx - prev_idx) > max_lookback_bars:
                        break # Too old
                        
                    # BULLISH DIVERGENCE:
                    # RSI Higher Low: curr_rsi > prev_rsi
                    # Price Lower Low: curr_price_low < prev_price
                    if curr_rsi > prev_rsi and curr_price_low < prev_price:
                        # Mark divergence
                        bull_div.iloc[signal_idx] = 1
                        logger.debug(f"🟢 BULLISH Divergence at index {signal_idx}: RSI {prev_rsi:.2f}→{curr_rsi:.2f} (higher low), Price {prev_price:.2f}→{curr_price_low:.2f} (lower low)")
                        break # Found the most recent valid divergence, stop searching
            
            # Add to history
            rsi_pivot_lows.append({'idx': curr_idx, 'price': curr_price_low, 'rsi': curr_rsi})
            
            # Prune history to keep it manageable (optional, but good optimization)
            # Remove pivots older than max_lookback * 3 (safety margin)
            if len(rsi_pivot_lows) > 0:
                first_idx = rsi_pivot_lows[0]['idx']
                if (curr_idx - first_idx) > (max_lookback_bars * 5):
                    rsi_pivot_lows.pop(0)

        # -------------------------------
        # 2. DETECT RSI PIVOT HIGH (Peak)
        # -------------------------------
        is_pivot_high = True
        
        # Check Left
        for k in range(1, pivot_lookback_left + 1):
            if rsi[i - k] >= curr_rsi:
                is_pivot_high = False
                break
        
        # Check Right
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
                        
                    # BEARISH DIVERGENCE:
                    # RSI Lower High: curr_rsi < prev_rsi
                    # Price Higher High: curr_price_high > prev_price
                    if curr_rsi < prev_rsi and curr_price_high > prev_price:
                        bear_div.iloc[signal_idx] = 1
                        logger.debug(f"🔴 BEARISH Divergence at index {signal_idx}: RSI {prev_rsi:.2f}→{curr_rsi:.2f} (lower high), Price {prev_price:.2f}→{curr_price_high:.2f} (higher high)")
                        break
            
            rsi_pivot_highs.append({'idx': curr_idx, 'price': curr_price_high, 'rsi': curr_rsi})
            
            if len(rsi_pivot_highs) > 0:
                first_idx = rsi_pivot_highs[0]['idx']
                if (curr_idx - first_idx) > (max_lookback_bars * 5):
                    rsi_pivot_highs.pop(0)

    # Log summary
    num_bullish = bull_div.sum()
    num_bearish = bear_div.sum()
    if num_bullish > 0 or num_bearish > 0:
        logger.info(f"📊 Divergences detected: {num_bullish} Bullish, {num_bearish} Bearish")
    
    return bull_div, bear_div


# ============================================================
# ✅ KELTNER CHANNELS
# ============================================================


def keltner_channels(
    df: pd.DataFrame,
    length: int = cfg.KC_LENGTH,
    mult: float = cfg.KC_MULT,
    source: str = cfg.KC_SOURCE,
    use_exp: bool = cfg.KC_USE_EXP,
    bands_style: str = cfg.KC_BANDS_STYLE,
    atr_length: int = cfg.KC_ATR_LENGTH,
) -> pd.DataFrame:
    """
    Compute Keltner Channels based on Pine Script logic.
    
    :param df: DataFrame with High, Low, Close
    :param length: Length for the Moving Average (Basis)
    :param mult: Multiplier for the Bands
    :param source: Column name for source price (default "Close")
    :param use_exp: If True, use EMA for Basis; otherwise SMA
    :param bands_style: "Average True Range" | "True Range" | "Range"
    :param atr_length: Length for ATR if style is "Average True Range"
    :return: DataFrame with KC_Upper, KC_Lower, KC_Basis
    """
    df = df.copy()
    src = pd.to_numeric(df[source], errors="coerce").fillna(0)
    high = pd.to_numeric(df["High"], errors="coerce").fillna(0)
    low = pd.to_numeric(df["Low"], errors="coerce").fillna(0)
    close = pd.to_numeric(df["Close"], errors="coerce").fillna(0)

    # 1. Calculate Basis (MA)
    if use_exp:
        ma = src.ewm(span=length, adjust=False).mean()
    else:
        ma = src.rolling(window=length).mean()

    # 2. Calculate Range MA (rangema)
    # Pine: rangema = BandsStyle == "True Range" ? ta.tr(true) : BandsStyle == "Average True Range" ? ta.atr(atrlength) : ta.rma(high - low, length)
    
    # Calculate True Range (TR)
    # TR = max(high-low, abs(high-prev_close), abs(low-prev_close))
    # Using pandas checks
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    if bands_style == "True Range":
        rangema = tr
    elif bands_style == "Average True Range":
        # ta.atr(atrlength) is RMA(tr, atrlength)
        # Pandas ewm alpha=1/length matches RMA
        rangema = tr.ewm(alpha=1/atr_length, adjust=False).mean()
    elif bands_style == "Range":
        # ta.rma(high - low, length)
        # rma of (high - low)
        hl_diff = high - low
        rangema = hl_diff.ewm(alpha=1/length, adjust=False).mean()
    else:
        # Default fallback to ATR if unknown style
        rangema = tr.ewm(alpha=1/atr_length, adjust=False).mean()

    # 3. Calculate Bands
    upper = ma + rangema * mult
    lower = ma - rangema * mult

    df["KC_Basis"] = ma
    df["KC_Upper"] = upper
    df["KC_Lower"] = lower
    
    return df




# ============================================================
# ✅ TRADING ZONES (CONFLUENCE)
# ============================================================


def get_trading_zones(
    df: pd.DataFrame,
    ut_a: int = cfg.TRADING_ZONES_UT_A,
    ut_c: int = cfg.TRADING_ZONES_UT_C,
    avg: int = cfg.TRADING_ZONES_AVG,
) -> pd.DataFrame:
    """
    Determine Buy/Sell zones based on confluence of indicators:
    - UT Bot Alerts
    - Trend Magic
    - Keltner Channels (Basis)
    
    Logic:
    - BUY ZONE: UT_Signal == 'BUY' and Trend_Direction == 1 and Close > Keltner_Basis
    - SELL ZONE: UT_Signal == 'SELL' and Trend_Direction == -1 and Close < Keltner_Basis
    """
    df = df.copy()
    
    # 1. UT Bot
    df_ut = ut_bot_signals(df, a=ut_a, c=ut_c)
    
    # 2. Trend Magic
    df_tm = trend_magic(df, atr_period=avg)
    
    # 3. Keltner Channels
    df_kc = keltner_channels(df, length=avg)
    
    # Conditions
    ut_pos = df_ut["Position"] 
    tm_dir = df_tm["Direction"]
    kc_basis = df_kc["KC_Basis"]
    close = df["Close"]
    
    # Define Zones
    zones =  pd.Series("NEUTRAL", index=df.index)
    
    buy_cond = (ut_pos == 1) & (tm_dir == 1) & (close > kc_basis)
    sell_cond = (ut_pos == -1) & (tm_dir == -1) & (close < kc_basis)
    
    zones[buy_cond] = "BUY ZONE"
    zones[sell_cond] = "SELL ZONE"
    
    df["Zone"] = zones
    df["UT_Signal"] = df_ut["Signal"]
    df["TM_Direction"] = tm_dir
    df["KC_Basis"] = kc_basis
    
    return df



# ============================================================
# ✅ STARC BANDS
# ============================================================


def starc_bands(
    df: pd.DataFrame,
    ma_length: int = cfg.STARC_MA_LENGTH,
    atr_length: int = cfg.STARC_ATR_LENGTH,
    k: float = cfg.STARC_K,
    source: str = cfg.STARC_SOURCE,
) -> pd.DataFrame:
    """
    STARC Bands (Stoller Average Range Channels).
    
    Upper = SMA(source, ma_length) + (ATR(atr_length) * k)
    Lower = SMA(source, ma_length) - (ATR(atr_length) * k)
    """
    df = df.copy()
    src = pd.to_numeric(df[source], errors="coerce").fillna(0)
    
    # Calculate SMA
    ma = src.rolling(window=ma_length).mean()
    
    # Calculate ATR
    # Using ta library to match other indicators
    atr_indicator = ta.volatility.AverageTrueRange(
        high=df["High"], low=df["Low"], close=df["Close"], window=atr_length
    )
    atr = atr_indicator.average_true_range()
    
    up_band = ma + (atr * k)
    dn_band = ma - (atr * k)
    
    return pd.DataFrame({
        "STARC_MA": ma,
        "STARC_Band_Up": up_band,
        "STARC_Band_Dn": dn_band
    })


# ============================================================
# ✅ SLOPE & ANGLE
# ============================================================


def calculate_slope_and_angle(series: pd.Series, period: int = 5) -> pd.DataFrame:
    """
    Production-grade rolling regression slope with strategy signals.
    TradingView / PineScript equivalent.

    Input:
        series : pd.Series
            Indicator series (ZLEMA / HMA / McGinley / MA etc.)
        period : int
            Lookback window

    Output columns:
        - slope        : OLS regression slope
        - angle        : slope angle in degrees (visual)
        - trend        : +1 uptrend | -1 downtrend | 0 flat
        - slope_flip   : True when slope changes sign
        - long_signal  : Entry long condition
        - short_signal : Entry short condition
    """

    series = pd.to_numeric(series, errors="coerce")

    n = period
    x = np.arange(n)
    x_mean = x.mean()
    x_demeaned = x - x_mean
    denom = np.sum(x_demeaned ** 2)

    y = series.values
    slopes = np.full(len(y), np.nan)

    for i in range(n - 1, len(y)):
        y_window = y[i - n + 1 : i + 1]

        # Skip incomplete windows
        if np.any(np.isnan(y_window)):
            continue

        y_mean = y_window.mean()
        slopes[i] = np.sum(x_demeaned * (y_window - y_mean)) / denom

    slope = pd.Series(slopes, index=series.index)

    # Angle (visual only)
    angle = np.degrees(np.arctan(slope))

    # ---------------- STRATEGY LOGIC ---------------- #

    # Trend state
    trend = np.where(slope > 0, 1, np.where(slope < 0, -1, 0))
    trend = pd.Series(trend, index=series.index)

    # Slope sign flip (trend change)
    slope_flip = (slope * slope.shift(1) < 0)

    # Entry logic (clean & stable)
    long_signal = (
        (slope > 0) &
        (slope.shift(1) <= 0)
    )

    short_signal = (
        (slope < 0) &
        (slope.shift(1) >= 0)
    )

    return pd.DataFrame(
        {
            "Slope": slope,
            "Angle": angle,
            "Trend": trend,
            "SlopeFlip": slope_flip,
            "LongSignal": long_signal,
            "ShortSignal": short_signal,
        },
        index=series.index,
    )

def regression_slope(
    series: pd.Series,
    period: int = 14,
    atr: Optional[pd.Series] = None,
    normalize_atr: bool = True
) -> pd.DataFrame:
    """
    Production-grade rolling linear regression slope (TradingView-compatible).

    - Uses local x = [0 .. period-1]
    - Exact OLS regression slope
    - Optional ATR-normalized slope (recommended for trading)

    Parameters
    ----------
    series : pd.Series
        Input price or indicator series
    period : int
        Regression lookback window
    atr : pd.Series, optional
        ATR series for normalization (same index)
    normalize_atr : bool
        Whether to normalize slope by ATR

    Returns
    -------
    pd.DataFrame with columns:
        - slope
        - slope_atr (if atr provided)
        - angle_deg
    """

    series = pd.to_numeric(series, errors="coerce")

    n = period
    x = np.arange(n)
    x_mean = x.mean()
    x_demeaned = x - x_mean
    denom = np.sum(x_demeaned ** 2)

    y = series.values
    slopes = np.full(len(y), np.nan)

    for i in range(n - 1, len(y)):
        y_window = y[i - n + 1 : i + 1]

        if np.any(np.isnan(y_window)):
            continue

        y_mean = y_window.mean()
        slopes[i] = np.sum(x_demeaned * (y_window - y_mean)) / denom

    slope = pd.Series(slopes, index=series.index)

    # Angle (for visualization only)
    angle = np.degrees(np.arctan(slope))

    # ATR-normalized slope (TRADING RELEVANT)
    if normalize_atr and atr is not None:
        atr = pd.to_numeric(atr, errors="coerce")
        slope_atr = slope / atr.replace(0, np.nan)
    else:
        slope_atr = None

    return pd.DataFrame(
        {
            "slope": slope,
            "slope_atr": slope_atr,
            "angle_deg": angle,
        },
        index=series.index,
    )

# ============================================================
# ✅ EXPORTS
# ============================================================

__all__ = [
    "hull_moving_average",
    "warmup_hull_with_historical",
    "mcginley",
    "warmup_mcginley_with_historical",
    "zlema",
    "warmup_zlema_with_historical",
    "trend_magic",
    "compute_trend_magic",
    "ut_bot_signals",
    "bollinger_bands",
    "rsi_indicator",
    "rsi_ma",
    "detect_divergences",
    "keltner_channels",
    "get_trading_zones",
    "starc_bands",
    "calculate_slope_and_angle",
    "regression_slope",
]
