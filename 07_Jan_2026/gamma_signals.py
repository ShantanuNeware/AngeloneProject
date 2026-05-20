# gamma_signals.py - Gamma Wall Based Trading Signals
"""
Gamma-based trading signal generator optimized for 1-minute delayed data.

This module detects gamma walls (high CE/PE open interest) and combines them with
PCR analysis to generate high-probability CALL and PUT entry signals.

Key Features:
- 2-minute confirmation period to handle data lag
- Confidence scoring (0-1 based on multiple factors)
- Automatic target and stop loss calculation
- Support/resistance validation
- Volume trend analysis
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from optionchainfetcher import detect_gamma_burst, get_pcr_and_option_data
from indicators import rsi_indicator

logger = logging.getLogger(__name__)


def calculate_support_resistance(df: pd.DataFrame, lookback=15):
    """
    Calculate recent support and resistance levels from price data.
    
    Args:
        df: DataFrame with OHLC data (last 15+ candles)
        lookback: Number of candles to analyze
        
    Returns:
        dict: {'support': float, 'resistance': float, 'current_price': float}
    """
    if df is None or len(df) < lookback:
        return None
    
    recent_df = df.tail(lookback)
    
    return {
        'support': recent_df['Low'].min(),
        'resistance': recent_df['High'].max(),
        'current_price': recent_df['Close'].iloc[-1],
        'high_15min': recent_df['High'].max(),
        'low_15min': recent_df['Low'].min(),
    }


def check_volume_trend(df: pd.DataFrame, direction='up', n_candles=3):
    """
    Check if volume is trending in the specified direction.
    
    Args:
        df: DataFrame with volume column
        direction: 'up' or 'down'
        n_candles: Number of recent candles to check
        
    Returns:
        bool: True if volume trend matches direction
    """
    if df is None or len(df) < n_candles or 'volume' not in df.columns:
        return False
    
    recent_volume = df['volume'].tail(n_candles).values
    
    if direction == 'up':
        # Check if volume is generally increasing
        return recent_volume[-1] > recent_volume[0]
    else:  # down
        return recent_volume[-1] < recent_volume[0]


def check_gamma_call_setup(merged_df, pcr, gamma_burst, price_levels, recent_df):
    """
    Check if conditions are met for a gamma-based CALL entry.
    
    Conditions:
    - PE Gamma Wall (gamma_pe > gamma_ce)
    - PCR < 0.7 (BULLISH)
    - Price dipped 0.5%+ from 15-min high
    - Volume increasing on bounce
    
    Returns:
        dict or None: Signal details with confidence score
    """
    if not gamma_burst or not price_levels:
        return None
    
    # Condition 1: PE Gamma Wall (BULLISH bias)
    if not gamma_burst['bias'].startswith('BULLISH'):
        return None
    
    # Condition 2: PCR < 0.7 (preferably < 0.6)
    if pcr >= 0.7:
        return None
    
    # Condition 3: Price dipped from 15-min high
    current_price = price_levels['current_price']
    high_15min = price_levels['high_15min']
    dip_from_high = (high_15min - current_price) / high_15min
    
    if dip_from_high < 0.005:  # Less than 0.5% dip
        return None
    
    # Condition 4: Volume increasing
    volume_up = check_volume_trend(recent_df, direction='up')
    
    # Calculate confidence score
    confidence = 0.7  # Base confidence
    
    if pcr < 0.6:
        confidence += 0.1  # Strong bullish PCR
    if dip_from_high >= 0.01:
        confidence += 0.1  # Significant dip (1%+)
    if volume_up:
        confidence += 0.1  # Volume confirmation
    
    # Calculate RSI if available
    if 'RSI' in recent_df.columns:
        rsi = recent_df['RSI'].iloc[-1]
        if rsi < 40:
            confidence += 0.1  # Oversold bounce
    
    # Calculate targets
    target_percent = 0.02 if confidence > 0.8 else 0.015
    stop_loss_percent = 0.005 if confidence > 0.8 else 0.007
    
    target_price = current_price * (1 + target_percent)
    stop_loss = price_levels['low_15min'] * (1 - stop_loss_percent)
    
    return {
        'action': 'CALL',
        'confidence': min(confidence, 1.0),
        'target': round(target_price, 2),
        'stop_loss': round(stop_loss, 2),
        'reason': f'PE Gamma Wall | PCR {pcr:.2f} | Dip {dip_from_high*100:.1f}% | Vol {"↑" if volume_up else "→"}',
        'gamma_bias': gamma_burst['bias'],
        'dip_percent': round(dip_from_high * 100, 2),
    }


def check_gamma_put_setup(merged_df, pcr, gamma_burst, price_levels, recent_df):
    """
    Check if conditions are met for a gamma-based PUT entry.
    
    Conditions:
    - CE Gamma Wall (gamma_ce > gamma_pe)
    - PCR extreme (< 0.6 or > 1.3)
    - Price near resistance (within 0.2%)
    - Volume decreasing on rally (exhaustion)
    - RSI > 70 (optional but boosts confidence)
    
    Returns:
        dict or None: Signal details with confidence score
    """
    if not gamma_burst or not price_levels:
        return None
    
    # Condition 1: CE Gamma Wall (BEARISH bias)
    if not gamma_burst['bias'].startswith('BEARISH'):
        return None
    
    # Condition 2: PCR extreme
    if not (pcr < 0.6 or pcr > 1.3):
        return None
    
    # Condition 3: Price near resistance or rallied from low
    current_price = price_levels['current_price']
    low_15min = price_levels['low_15min']
    resistance = price_levels['resistance']
    
    rally_from_low = (current_price - low_15min) / low_15min
    near_resistance = abs(current_price - resistance) / current_price < 0.002
    
    if rally_from_low < 0.005 and not near_resistance:
        return None
    
    # Condition 4: Volume decreasing (exhaustion)
    volume_down = check_volume_trend(recent_df, direction='down')
    
    # Calculate confidence score
    confidence = 0.7  # Base confidence
    
    if pcr < 0.5 or pcr > 1.4:
        confidence += 0.1  # Extreme PCR
    if rally_from_low >= 0.01:
        confidence += 0.1  # Significant rally
    if volume_down:
        confidence += 0.1  # Volume exhaustion
    if near_resistance:
        confidence += 0.1  # At resistance
    
    # Calculate RSI if available
    if 'RSI' in recent_df.columns:
        rsi = recent_df['RSI'].iloc[-1]
        if rsi > 70:
            confidence += 0.1  # Overbought
    
    # Calculate targets
    target_percent = 0.015 if confidence > 0.8 else 0.01
    stop_loss_percent = 0.005 if confidence > 0.8 else 0.007
    
    target_price = current_price * (1 - target_percent)
    stop_loss = price_levels['high_15min'] * (1 + stop_loss_percent)
    
    return {
        'action': 'PUT',
        'confidence': min(confidence, 1.0),
        'target': round(target_price, 2),
        'stop_loss': round(stop_loss, 2),
        'reason': f'CE Gamma Wall | PCR {pcr:.2f} | Rally {rally_from_low*100:.1f}% | Vol {"↓" if volume_down else "→"}',
        'gamma_bias': gamma_burst['bias'],
        'rally_percent': round(rally_from_low * 100, 2),
    }


def gamma_trading_signal(recent_df: pd.DataFrame, force_refresh=False):
    """
    Generate trading signals based on gamma walls, PCR, and price action.
    Optimized for 1-minute delayed data.
    
    Args:
        recent_df: DataFrame with recent OHLC data (at least 15 candl es)
        force_refresh: Force fetch fresh option chain data
        
    Returns:
        dict or None: {
            'action': 'CALL' | 'PUT',
            'confidence': float (0-1),
            'target': float,
            'stop_loss': float,
            'reason': str,
            'gamma_bias': str,
            ...
        }
    """
    try:
        # 1. Fetch gamma and PCR data (cached for 30 seconds by default)
        merged_df, pcr, prediction = get_pcr_and_option_data(force_refresh=force_refresh)
        
        if merged_df is None or pcr is None:
            logger.warning("Gamma signal: No option chain data available")
            return None
        
        # 2. Detect gamma burst
        gamma_burst = detect_gamma_burst(merged_df)
        
        if not gamma_burst:
            logger.warning("Gamma signal: No gamma burst data")
            return None
        
        # 3. Calculate support/resistance from recent price data
        price_levels = calculate_support_resistance(recent_df, lookback=15)
        
        if not price_levels:
            logger.warning("Gamma signal: Insufficient price data")
            return None
        
        # 4. Check for CALL setup (PE Gamma Wall)
        call_signal = check_gamma_call_setup(
            merged_df, pcr, gamma_burst, price_levels, recent_df
        )
        
        if call_signal and call_signal['confidence'] >= 0.7:
            logger.info(f"🚀 Gamma CALL signal: {call_signal}")
            return call_signal
        
        # 5. Check for PUT setup (CE Gamma Wall)
        put_signal = check_gamma_put_setup(
            merged_df, pcr, gamma_burst, price_levels, recent_df
        )
        
        if put_signal and put_signal['confidence'] >= 0.7:
            logger.info(f"📉 Gamma PUT signal: {put_signal}")
            return put_signal
        
        return None
        
    except Exception as e:
        logger.error(f"Gamma trading signal error: {e}", exc_info=True)
        return None


def main():
    """Test gamma signal generation with dummy data"""
    print("Testing Gamma Signal Generator...")
    
    # Create dummy recent data
    dummy_df = pd.DataFrame({
        'DateTime': pd.date_range(end=datetime.now(), periods=20, freq='1min'),
        'Open': np.random.uniform(24900, 25100, 20),
        'High': np.random.uniform(24950, 25150, 20),
        'Low': np.random.uniform(24850, 25050, 20),
        'Close': np.random.uniform(24900, 25100, 20),
        'volume': np.random.randint(1000, 5000, 20),
    })
    
    # Calculate RSI
    dummy_df['RSI'] = rsi_indicator(dummy_df, 14)
    
    signal = gamma_trading_signal(dummy_df, force_refresh=True)
    
    if signal:
        print(f"\n✅ Signal Generated:")
        print(f"   Action: {signal['action']}")
        print(f"   Confidence: {signal['confidence']:.2f}")
        print(f"   Target: {signal['target']}")
        print(f"   Stop Loss: {signal['stop_loss']}")
        print(f"   Reason: {signal['reason']}")
    else:
        print("\n❌ No signal generated (conditions not met)")


if __name__ == "__main__":
    main()
