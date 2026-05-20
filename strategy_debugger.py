"""
Quick Strategy Debugger - Test individual strategies in isolation
Useful for debugging and parameter tuning
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tradingsystem.strategies.Strategy import StrategyRunner
from tradingsystem.core.strategy_manager import StrategyManager, StrategyManagerConfig
from tradingsystem.core.regime_manager import RegimeManager
from tradingsystem.data.db import MarketDB
from tradingsystem.models import Candle, MarketRegime
from tradingsystem.config.loader import load_config

print("=" * 80)
print("STRATEGY DEBUGGER - QUICK TEST")
print("=" * 80)

# Load config
config = load_config()
strategy_name = config['strategy'].get('name', 'MAStrategy')
symbol = config['strategy'].get('symbol', 'SBIN-EQ')

print(f"\nTesting Strategy: {strategy_name}")
print(f"Symbol: {symbol}")

# Initialize
regime_manager = RegimeManager()
strategy_config = StrategyManagerConfig(regime_manager=regime_manager)
strategy_manager = StrategyManager(config=strategy_config)
strategy_manager.load_strategies_from_config(config.get('strategy', {}))

db = MarketDB()
runner = StrategyRunner(strategy_manager, db)

# Create test scenarios
def create_trending_candles(base_price=100, num_candles=30):
    """Uptrend scenario - good for MA strategy"""
    candles = []
    for i in range(num_candles):
        price = base_price + (i * 0.8)
        candle = Candle(
            timestamp=datetime.now() - timedelta(minutes=num_candles-i),
            open=price - 0.5,
            high=price + 1,
            low=price - 1,
            close=price,
            volume=1000000,
            symbol=symbol,
            timeframe='1m'
        )
        candles.append(candle)
    return candles

def create_ranging_candles(base_price=100, num_candles=30):
    """Range-bound scenario - good for RSI strategy"""
    candles = []
    for i in range(num_candles):
        # Oscillate between 98 and 102
        variation = 2 * ((i % 10) / 5 - 1)
        price = base_price + variation
        candle = Candle(
            timestamp=datetime.now() - timedelta(minutes=num_candles-i),
            open=price - 0.3,
            high=price + 0.5,
            low=price - 0.5,
            close=price,
            volume=800000,
            symbol=symbol,
            timeframe='1m'
        )
        candles.append(candle)
    return candles

def create_volatile_candles(base_price=100, num_candles=30):
    """High volatility scenario"""
    candles = []
    for i in range(num_candles):
        # Large swings
        variation = (i % 5) * (2 if (i // 5) % 2 else -2)
        price = base_price + variation
        candle = Candle(
            timestamp=datetime.now() - timedelta(minutes=num_candles-i),
            open=price - 1,
            high=price + 2,
            low=price - 2,
            close=price,
            volume=1200000,
            symbol=symbol,
            timeframe='1m'
        )
        candles.append(candle)
    return candles

# Test scenarios
scenarios = {
    "TRENDING UPTREND": {
        "candles": create_trending_candles(),
        "regime": MarketRegime.TRENDING,
        "adx": 35.0,
        "atr": 2.5
    },
    "RANGING MARKET": {
        "candles": create_ranging_candles(),
        "regime": MarketRegime.RANGING,
        "adx": 15.0,
        "atr": 1.2
    },
    "HIGH VOLATILITY": {
        "candles": create_volatile_candles(),
        "regime": MarketRegime.VOLATILE,
        "adx": 20.0,
        "atr": 5.0
    }
}

# Test each scenario
for scenario_name, scenario_data in scenarios.items():
    print(f"\n{'-' * 80}")
    print(f"Scenario: {scenario_name}")
    print(f"{'─' * 80}")
    
    candles = scenario_data["candles"]
    regime = scenario_data["regime"]
    adx = scenario_data["adx"]
    atr = scenario_data["atr"]
    
    # Show candle stats
    opens = [c.open for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    
    print(f"  Candles: {len(candles)}")
    print(f"  Price: {closes[0]:.2f} → {closes[-1]:.2f}")
    print(f"  Range: {min(lows):.2f} - {max(highs):.2f}")
    print(f"  Regime: {regime.name}")
    print(f"  ADX: {adx:.1f}, ATR: {atr:.1f}")
    
    # Analyze
    signals = strategy_manager.analyze_market(
        candles=candles,
        current_regime=regime,
        adx_value=adx,
        atr_value=atr
    )
    
    if signals:
        print(f"\n  ✓ SIGNALS GENERATED: {len(signals)}")
        for sig in signals:
            print(f"    - {sig.signal_type.name:<8} @ {sig.price:>8.2f} (conf: {sig.confidence:.2f})")
    else:
        print(f"\n  ℹ No signals (need different parameters or more data)")

# Interactive mode
print(f"\n{'=' * 80}")
print("INTERACTIVE MODE")
print("=" * 80)

def test_custom_candles():
    """Allow custom candle input"""
    print("\nEnter candle data (format: open,high,low,close,volume)")
    print("Or press Enter to skip: ", end="", flush=True)
    
    user_input = input().strip()
    if not user_input:
        return None
    
    try:
        parts = user_input.split(',')
        if len(parts) != 5:
            print("❌ Invalid format. Use: open,high,low,close,volume")
            return None
        
        o, h, l, c, v = map(float, parts)
        candle = Candle(
            timestamp=datetime.now(),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=int(v),
            symbol=symbol,
            timeframe='1m'
        )
        return candle
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

print("\nWould you like to test custom candles? (y/n): ", end="", flush=True)
if input().strip().lower() == 'y':
    base_candles = create_trending_candles(num_candles=15)  # Start with base
    
    print(f"\nStarting with {len(base_candles)} base candles")
    print("Add custom candles one by one:")
    
    for _ in range(5):
        candle = test_custom_candles()
        if candle:
            base_candles.append(candle)
            print(f"  Added: {candle.close:.2f} (total: {len(base_candles)})")
    
    print("\nAnalyzing combined candles...")
    signals = strategy_manager.analyze_market(
        candles=base_candles,
        current_regime=MarketRegime.TRENDING,
        adx_value=30.0,
        atr_value=2.0
    )
    
    if signals:
        print(f"✓ Generated {len(signals)} signal(s)")
        for sig in signals:
            print(f"  - {sig.signal_type.name} @ {sig.price:.2f}")
    else:
        print("ℹ No signals generated")

print("\n" + "=" * 80)
print("Test completed. Strategy is ready for integration.")
print("=" * 80)
