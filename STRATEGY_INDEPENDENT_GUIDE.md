# Strategy Runner - Independent Execution Guide

## Problem Fixed
The `Strategy.py` file couldn't be run independently because it was missing the sys.path configuration needed to import the `tradingsystem` module.

### What Changed
Added the following at the top of `tradingsystem/strategies/Strategy.py`:

```python
import sys
from pathlib import Path

# Add project root to sys.path to allow independent execution
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
```

This ensures the `tradingsystem` package can be found regardless of where the script is executed from.

---

## How to Run Strategy Independently

### Method 1: Using Test Script (Recommended)
```bash
cd e:\WORKSPACE\NewProjects\New_project_Self
python test_strategy_runner.py
```

This runs a comprehensive test of the StrategyRunner with:
- Component initialization
- Sample candle generation
- Strategy analysis
- Signal persistence
- Historical signal checking

### Method 2: Direct Import
```bash
python -c "from tradingsystem.strategies.Strategy import StrategyRunner; print('✓ Ready')"
```

### Method 3: From Your Own Script
```python
from tradingsystem.strategies.Strategy import StrategyRunner, create_runner_from_engine
from tradingsystem.core.strategy_manager import StrategyManager
from tradingsystem.data.db import MarketDB

# Initialize components
db = MarketDB()
strategy_manager = StrategyManager(config=your_config)
runner = StrategyRunner(strategy_manager, db)

# Run analysis
signals = runner.run_and_persist(
    candles=your_candles,
    regime=market_regime,
    adx_value=35.0,
    atr_value=2.5
)
```

---

## StrategyRunner Methods

### 1. `run_and_persist(candles, regime, adx_value, atr_value)`
Runs all active strategies and persists results to database.

**Input:**
- `candles`: List[Candle] - Historical candle data
- `regime`: MarketRegime - Current market regime
- `adx_value`: float - ADX indicator value
- `atr_value`: float - ATR indicator value

**Output:**
- `List[Signal]` - Generated trading signals

**Example:**
```python
signals = runner.run_and_persist(
    candles=sample_candles,
    regime=MarketRegime.TRENDING,
    adx_value=35.0,
    atr_value=2.5
)
print(f"Generated {len(signals)} signals")
```

### 2. `check_historical_signals(lookback_hours=24)`
Checks recent entries in strategy_history table for unresolved positions.

**Output:**
```python
{
    'in_trade': bool,              # Currently in a trade?
    'trade_direction': str|None,   # 'CALL', 'PUT', or None
    'entry_time': datetime|None,   # When entry occurred
    'entry_price': float|None      # Entry price
}
```

### 3. `vectorized_analysis(candles, historical_state=None, persist=False)` 
Produces pandas DataFrame with indicators and strategy signals.

**Requirements:**
- pandas must be installed: `pip install pandas`

**Output:**
- pandas DataFrame with indicator and signal columns

**Example:**
```python
df = runner.vectorized_analysis(
    candles=sample_candles,
    persist=True  # Write to database
)
print(df[['DateTime', 'Close', 'ma_signal', 'rsi_signal']])
```

---

## Data Flow When Running Strategy

```
Input: Candles + Market Regime
   ↓
StrategyManager.analyze_market()
   ↓
Route to appropriate strategy (MA/RSI/BB)
   ↓
Calculate indicators
   ↓
Generate Signal (BUY/SELL/HOLD)
   ↓
run_and_persist() writes to database
   ↓
Output: List[Signal]
```

---

## Testing Scenarios

### Scenario 1: Test with Trending Market
```python
signals = runner.run_and_persist(
    candles=trending_candles,
    regime=MarketRegime.TRENDING,
    adx_value=35.0,  # Strong trend
    atr_value=2.5
)
```

### Scenario 2: Test with Ranging Market
```python
signals = runner.run_and_persist(
    candles=ranging_candles,
    regime=MarketRegime.RANGING,
    adx_value=15.0,  # Weak trend
    atr_value=1.2
)
```

### Scenario 3: Test with Volatile Market
```python
signals = runner.run_and_persist(
    candles=volatile_candles,
    regime=MarketRegime.VOLATILE,
    adx_value=20.0,
    atr_value=5.0  # High volatility
)
```

---

## Troubleshooting

### Issue: "No module named 'tradingsystem'"
**Solution:** Ensure you're running from the workspace root:
```bash
cd e:\WORKSPACE\NewProjects\New_project_Self
python your_script.py
```

### Issue: "No signals generated"
**Possible causes:**
1. Not enough candle history (strategies need 20+ candles)
2. Strategy confidence threshold too high
3. Market conditions don't match strategy logic
4. Parameters not optimized for current market

**Debug:**
```python
# Check strategy manager directly
signal = strategy_manager.analyze_market(
    candles=candles[-20:],
    current_regime=MarketRegime.TRENDING,
    adx_value=35.0,
    atr_value=2.5
)
print(f"Signal: {signal}")
```

### Issue: "Database error"
**Solution:** Ensure database file exists:
```bash
# Check database
ls tradingsystem/data/*.db

# Or reinitialize
python -c "from tradingsystem.data.db import MarketDB; MarketDB()"
```

---

## Quick Run Examples

### Run all checks:
```bash
# 1. Check data flow
python data_flow_checker.py

# 2. Detailed analysis
python data_flow_analysis.py

# 3. Test strategy runner
python test_strategy_runner.py
```

### Import and use:
```python
from tradingsystem.strategies.Strategy import StrategyRunner
from tradingsystem.config.loader import load_config

config = load_config()
# Your code here...
```

---

## Key Files Modified
- `tradingsystem/strategies/Strategy.py` - Added sys.path configuration
- `test_strategy_runner.py` - New comprehensive test script
- `data_flow_checker.py` - Data flow validation
- `data_flow_analysis.py` - Architecture documentation

---

## Next Steps
1. ✓ Strategy can run independently
2. → Integrate with TradingEngine for live trading
3. → Add real market data feed
4. → Monitor and optimize signal quality
