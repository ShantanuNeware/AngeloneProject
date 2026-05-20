# Trading System

A lightweight, real-time algorithmic trading system for Indian stock market (Angel One broker).

## Overview

```
┌─────────────────┐
│  Broker Feeds   │ (Real-time market data from Angel One)
│  (NIFTY)        │
└────────┬────────┘
         │
         ↓
┌─────────────────┐      ┌──────────────────┐
│  Market Data    │  →   │  Regime Manager  │ (Detect if trending, ranging, or volatile)
│  (Candles)      │      └──────────────────┘
└────────┬────────┘
         │
         ↓
┌──────────────────────────────────────┐
│  Strategy Selection (based on regime) │
│  • TRENDING → MA Crossover           │
│  • RANGING → RSI Mean Reversion      │
│  • VOLATILE → Bollinger Bands        │
└────────────┬─────────────────────────┘
             │
             ↓
    ┌─────────────────┐
    │  Trading Signal │ (BUY, SELL, HOLD)
    └────────┬────────┘
             │
             ↓
┌─────────────────────────┐
│  Execution Manager      │ (Places actual orders)
│  (If enabled in config) │
└─────────────────────────┘
```

## Quick Start

```bash
# Run the system
python tradingsystem/main_refactored.py

# Stop with Ctrl+C
```

## What Happens

1. **Loads Config** → Reads `tradingsystem/config/default.json`
2. **Logs Into Broker** → Connects to Angel One
3. **Fetches Market Data** → Gets NIFTY candles every N seconds
4. **Detects Regime** → Analyzes market using ADX and ATR indicators
5. **Selects Strategy** → Chooses strategy based on market condition
6. **Generates Signal** → MA, RSI, or BB strategy analyzes prices
7. **Executes Order** → Places order on Angel One (if enabled)
8. **Logs Everything** → Saves all events to `logs/YYYY-MM-DD/`

## Configuration

**File:** `tradingsystem/config/default.json`

Key settings:

```json
{
  "brokers": {
    "angleone": {
      "api_key": "YOUR_API_KEY",
      "username": "YOUR_USERNAME",
      "password": "YOUR_PASSWORD",
      "factor2": "YOUR_TOTP_SECRET"
    }
  },
  "strategy": {
    "timeframe": "1m",
    "poll_interval_seconds": 60,
    "data_fetch_minutes": 60
  },
  "system": {
    "execute_signals": false    // CAREFUL: Set to true for REAL orders
  }
}
```

### Configuration Options

| Setting | Example | Description |
|---------|---------|-------------|
| `timeframe` | `"1m"`, `"5m"`, `"1h"` | Candle period (1m, 5m, 15m, 1h, 4h, 1d) |
| `poll_interval_seconds` | `60` | How often to check for new data (seconds) |
| `data_fetch_minutes` | `60` | How many minutes of historical data to fetch (1 = last 1 minute, 60 = last hour) |
| `execute_signals` | `false` | Set to `true` only for live trading with real money |

**Example: Fetch only 1 minute of data:**
```json
"data_fetch_minutes": 1
```

**Example: Fetch 5 minutes of data:**
```json
"data_fetch_minutes": 5
```

## Three Strategies

### 1. MA Crossover (TRENDING Market)

Uses 9 and 21 period moving averages.

```
Entry: Price > fast MA + pullback confirmation
Exit: Fast MA < slow MA
```

- **Best When:** ADX > 25 (strong trend)
- **File:** `tradingsystem/strategies/ma_strategy.py`

### 2. RSI Mean Reversion (RANGING Market)

Buys oversold (RSI < 30), sells overbought (RSI > 70).

```
Entry: RSI < 30 + price bounce
Exit: RSI > 70
```

- **Best When:** ADX < 20 (no trend)
- **File:** `tradingsystem/strategies/rsi_strategy.py`

### 3. Bollinger Bands (VOLATILE Market)

Trades breakouts from volatility extremes.

```
Entry: Price breaks above/below outer bands + volume
```

- **Best When:** High ATR
- **File:** `tradingsystem/strategies/bb_strategy.py`

## Project Structure

```
tradingsystem/
├── main_refactored.py        # ENTRY POINT - Run this
├── config/
│   ├── default.json          # Configuration
│   └── loader.py             # Config loader
├── core/
│   ├── regime_manager.py     # Detect market regime
│   ├── strategy_manager.py   # Select strategy
│   ├── execution_manager.py  # Execute orders
│   └── events.py             # Event system
├── strategies/
│   ├── base.py               # Base class
│   ├── ma_strategy.py        # Moving Average
│   ├── rsi_strategy.py       # RSI
│   └── bb_strategy.py        # Bollinger Bands
├── broker/
│   ├── angelone_session.py   # Login
│   └── order_manager.py      # Place orders
├── data/
│   ├── angelone_fetcher.py   # Fetch data
│   └── db.py                 # Database
├── indicators/
│   ├── adx.py, atr.py, etc.  # Indicators
└── models/
    ├── candle.py             # OHLCV
    ├── signal.py             # Signals
    └── regime.py             # Regimes
```

## How It Works

1. **Regime Detection** (`regime_manager.py`)
   - Uses ADX for trend strength (0-100)
   - Uses ATR for volatility (0-∞)
   - Returns: TRENDING, RANGING, or VOLATILE

2. **Strategy Selection** (`strategy_manager.py`)
   - TRENDING → Use MA Crossover
   - RANGING → Use RSI
   - VOLATILE → Use Bollinger Bands

3. **Signal Generation** (strategy files)
   - Each strategy has `analyze()` method
   - Returns Signal with BUY/SELL/HOLD
   - Includes price, confidence, reason

4. **Order Execution** (`execution_manager.py`)
   - Listens for signals
   - Places orders if enabled
   - Logs everything

## Key Concepts

### Signal
```python
Signal(
    strategy_name="ma_strategy",
    symbol="NIFTY",
    signal_type=SignalType.BUY,
    price=20500.50,
    confidence=0.85,  # 0.0 to 1.0
    regime="trending"
)
```

### Candle (OHLCV)
```python
Candle(
    symbol="NIFTY",
    timeframe="1m",
    open=20400.0,
    high=20550.0,
    low=20350.0,
    close=20500.0,
    volume=100000
)
```

### Market Regime
- **TRENDING** → ADX > 25 (strong directional)
- **RANGING** → ADX < 20 (bouncing levels)
- **VOLATILE** → High ATR (large swings)

## Understanding a Strategy

All strategies follow same pattern:

```python
def analyze(self, candles, regime, adx_value=0, atr_value=0, **kwargs):
    # 1. Validate input
    if not self._validate_candles(candles, min_count=X):
        return None
    
    # 2. Check if strategy applies to this regime
    if not is_right_regime(regime):
        return None
    
    # 3. Calculate indicators
    indicator_value = self._calculate(candles)
    
    # 4. Generate signal
    if signal_condition_met:
        return Signal(
            strategy_name="my_strategy",
            symbol=candles[-1].symbol,
            signal_type=SignalType.BUY,
            price=candles[-1].close,
            confidence=0.75,
            regime=regime.value
        )
    
    return None  # No signal
```

## Indicators Used

| Indicator | Formula | Interpretation |
|-----------|---------|-----------------|
| ADX (14) | Average Directional Index | Trend strength: 0-100 |
| ATR (14) | Average True Range | Volatility: price swing size |
| MA (9, 21) | Simple Moving Average | Trend direction |
| RSI (14) | Relative Strength Index | Momentum: 0-100 |
| BB (20, 2σ) | Bollinger Bands | Volatility bands |

## Safety Features

✅ `execute_signals: false` by default (simulation only)  
✅ Each strategy has risk/reward limits  
✅ All events logged to `logs/YYYY-MM-DD/`  
✅ Graceful shutdown with Ctrl+C  
✅ Configuration-based (no code changes needed)  

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No data from broker | Check API key, token, internet |
| ModuleNotFoundError | Run from workspace root |
| Orders not executing | Check `execute_signals: true`, broker balance |
| Missing logs | Check `logs/` folder permissions |

## Creating a New Strategy

1. Create new file: `tradingsystem/strategies/my_strategy.py`
2. Inherit from `BaseStrategy`
3. Implement `analyze()` method
4. Return `Signal` or `None`
5. Add to `main_refactored.py` setup

Example:
```python
from tradingsystem.strategies import BaseStrategy
from tradingsystem.models import Signal, SignalType

class MyStrategy(BaseStrategy):
    def analyze(self, candles, regime, adx_value=0, **kwargs):
        if len(candles) < 5:
            return None
        
        if some_condition(candles):
            return Signal(
                strategy_name="my_strategy",
                symbol=candles[-1].symbol,
                signal_type=SignalType.BUY,
                price=candles[-1].close,
                confidence=0.70,
                regime=regime.value
            )
        return None
```

## Learning Path

1. ✅ Read this README
2. ✅ Run the system with `execute_signals: false`
3. ✅ Read `main_refactored.py` execution flow
4. ✅ Study one strategy (e.g., `ma_strategy.py`)
5. ✅ Check logs in `logs/YYYY-MM-DD/`
6. ✅ Paper trade
7. ✅ Only then: Set `execute_signals: true` for live trading

## Codebase Quality

- **No Over-Engineering:** Simple, readable code
- **Clear Separation:** Each module has one job
- **Hardcoded Defaults:** Best-practice parameters built-in
- **Minimal Complexity:** No unnecessary abstractions
- **Production Ready:** Handles errors gracefully

---

**Status:** Clean, simple, and working  
**Last Updated:** May 11, 2026
