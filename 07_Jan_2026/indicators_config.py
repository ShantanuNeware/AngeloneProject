# indicators_config.py

# ============================================================
# ✅ HULL MOVING AVERAGE
# ============================================================
HMA_PERIOD = 14
HMA_WARMUP_CANDLES = 20

# ============================================================
# ✅ MCGINLEY DYNAMIC
# ============================================================
MCGINLEY_PERIOD = 14
MCGINLEY_WARMUP_PERIOD = 10
MCGINLEY_WARMUP_CANDLES = 5
MCGINLEY_K = 0.6

# ============================================================
# ✅ TREND MAGIC
# ============================================================
TREND_MAGIC_ATR_PERIOD = 20

# ============================================================
# ✅ ZLEMA (Zero-Lag EMA)
# ============================================================
ZLEMA_PERIOD = 14
ZLEMA_WARMUP_PERIOD = 10
ZLEMA_WARMUP_CANDLES = 5

# ============================================================
# ✅ UT BOT ALERTS
# ============================================================
# No static defaults in function signature other than False for use_heikin, 
# but user specifically asked for "all paraments of indicators which are staic".
# The wrapper `get_trading_zones` uses 2, 1.

# ============================================================
# ✅ BOLLINGER BANDS
# ============================================================
BB_LENGTH = 20
BB_MULT = 2.0
BB_MA_TYPE = "EMA"
BB_OFFSET = 0

# ============================================================
# ✅ RSI & DIVERGENCES
# ============================================================
RSI_LENGTH = 7
RSI_SOURCE = "Close"
RSI_MA_TYPE = "EMA"
RSI_MA_LENGTH = 217

# More aggressive divergence detection to match TradingView
# Reduced lookback = faster signals, more divergences detected
DIVERGENCE_PIVOT_LOOKBACK_LEFT = 7      # Was 7 - now only needs 3 bars on left
DIVERGENCE_PIVOT_LOOKBACK_RIGHT = 2    # Was 7 - signals appear 2 bars after pivot (6 minutes on 3min chart)
DIVERGENCE_MAX_LOOKBACK_BARS = 60     # Was 60 - search further back for divergence patterns

# ============================================================
# ✅ KELTNER CHANNELS
# ============================================================
KC_LENGTH = 20
KC_MULT = 2.0
KC_SOURCE = "Close"
KC_USE_EXP = True
KC_BANDS_STYLE = "Average True Range"
KC_ATR_LENGTH = 10

# ============================================================
# ✅ TRADING ZONES (CONFLUENCE)
# ============================================================
TRADING_ZONES_UT_A = 2
TRADING_ZONES_UT_C = 1
TRADING_ZONES_AVG = 20

# ============================================================
# ✅ STARC BANDS
# ============================================================
STARC_MA_LENGTH = 5
STARC_ATR_LENGTH = 15
STARC_K = 1.33
STARC_SOURCE = "Close"
