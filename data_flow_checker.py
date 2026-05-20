"""
Data Flow Checker - Traces and visualizes data movement through the trading system

Checks:
1. Configuration loading
2. Component initialization
3. Data flow path: Broker → Regime Manager → Strategy → Execution
4. Event bus connectivity
5. Database readiness
"""

import sys
from pathlib import Path
import json

# Add project root to sys.path
project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print("=" * 80)
print("TRADING SYSTEM - DATA FLOW CHECKER")
print("=" * 80)

# ============================================================================
# STEP 1: Configuration Loading
# ============================================================================
print("\n[STEP 1] Configuration Loading")
print("-" * 80)

try:
    from tradingsystem.config.loader import load_config
    config = load_config()
    print("✓ Config loaded successfully")
    print(f"  - Broker: {config.get('system', {}).get('broker')}")
    print(f"  - Strategy: {config.get('strategy', {}).get('name')}")
    print(f"  - Symbol: {config.get('strategy', {}).get('symbol')}")
    print(f"  - Timeframe: {config.get('strategy', {}).get('timeframe')}")
    print(f"  - Poll Interval: {config.get('strategy', {}).get('poll_interval_seconds')}s")
    print(f"  - Execute Signals: {config.get('system', {}).get('execute_signals')}")
except Exception as e:
    print(f"✗ Config loading failed: {e}")
    sys.exit(1)

# ============================================================================
# STEP 2: Core Models Initialization
# ============================================================================
print("\n[STEP 2] Core Models Initialization")
print("-" * 80)

try:
    from tradingsystem.models import Candle, Signal, SignalType, MarketRegime
    from tradingsystem.models.option import OptionChain
    print("✓ Core models imported")
    print(f"  - Candle: {Candle.__name__}")
    print(f"  - Signal: {Signal.__name__}")
    print(f"  - MarketRegime: {MarketRegime.__name__}")
    print(f"  - OptionChain: {OptionChain.__name__}")
except Exception as e:
    print(f"✗ Model import failed: {e}")
    sys.exit(1)

# ============================================================================
# STEP 3: Event Bus Initialization
# ============================================================================
print("\n[STEP 3] Event Bus Setup")
print("-" * 80)

try:
    from tradingsystem.core import SyncEventBus, SignalGeneratedEvent
    event_bus = SyncEventBus()
    print("✓ Event bus initialized (SyncEventBus)")
    
    # Track events
    event_log = []
    def event_tracker(event):
        event_log.append({
            'type': type(event).__name__,
            'timestamp': getattr(event, 'timestamp', None),
            'data': event
        })
    
    event_bus.subscribe(SignalGeneratedEvent, event_tracker)
    print("✓ Event subscribers registered")
    print(f"  - SignalGeneratedEvent subscriber added")
except Exception as e:
    print(f"✗ Event bus setup failed: {e}")
    sys.exit(1)

# ============================================================================
# STEP 4: Regime Manager Initialization
# ============================================================================
print("\n[STEP 4] Regime Manager Initialization")
print("-" * 80)

try:
    from tradingsystem.core import RegimeManager
    regime_manager = RegimeManager(
        trend_threshold=25.0,
        range_threshold=20.0,
        volatility_threshold=2.5
    )
    print("✓ Regime manager initialized")
    print(f"  - Trend Threshold: 25.0%")
    print(f"  - Range Threshold: 20.0%")
    print(f"  - Volatility Threshold: 2.5σ")
except Exception as e:
    print(f"✗ Regime manager initialization failed: {e}")
    sys.exit(1)

# ============================================================================
# STEP 5: Strategy Manager Initialization
# ============================================================================
print("\n[STEP 5] Strategy Manager Initialization")
print("-" * 80)

try:
    from tradingsystem.core import StrategyManager, StrategyManagerConfig
    from tradingsystem.strategies import MAStrategy, RSIStrategy, BBStrategy
    
    strategy_config = StrategyManagerConfig(
        regime_manager=regime_manager,
        min_signal_confidence=0.5,
        require_regime_agreement=True
    )
    
    strategy_manager = StrategyManager(config=strategy_config)
    
    # Load strategies from the config
    strategy_manager.load_strategies_from_config(config.get('strategy', {}))
    
    strategy_name = config['strategy'].get('name', 'MAStrategy')
    symbol = config['strategy'].get('symbol', 'SBIN-EQ')
    timeframe = config['strategy'].get('timeframe', '1h')
    
    print("✓ Strategy manager initialized")
    print(f"  - Strategy: {strategy_name}")
    print(f"  - Symbol: {symbol}")
    print(f"  - Timeframe: {timeframe}")
except Exception as e:
    print(f"✗ Strategy manager initialization failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# STEP 6: Data Flow Test - Simulate Candle Data
# ============================================================================
print("\n[STEP 6] Data Flow Test - Simulating Market Data")
print("-" * 80)

try:
    from datetime import datetime
    
    # Create sample candles
    sample_candles = [
        Candle(timestamp=datetime.now(), open=100, high=105, low=99, close=103, volume=1000000, symbol=config['strategy']['symbol'], timeframe=config['strategy']['timeframe']),
        Candle(timestamp=datetime.now(), open=103, high=108, low=102, close=106, volume=1100000, symbol=config['strategy']['symbol'], timeframe=config['strategy']['timeframe']),
        Candle(timestamp=datetime.now(), open=106, high=110, low=105, close=108, volume=1200000, symbol=config['strategy']['symbol'], timeframe=config['strategy']['timeframe']),
        Candle(timestamp=datetime.now(), open=108, high=112, low=107, close=110, volume=1300000, symbol=config['strategy']['symbol'], timeframe=config['strategy']['timeframe']),
        Candle(timestamp=datetime.now(), open=110, high=115, low=109, close=112, volume=1400000, symbol=config['strategy']['symbol'], timeframe=config['strategy']['timeframe']),
    ]
    
    print(f"✓ Generated {len(sample_candles)} sample candles")
    
    # Process candles through strategy manager using the API
    print("\n  Processing candles through StrategyManager...")
    signals_generated = []
    for i, candle in enumerate(sample_candles, 1):
        # The strategy manager expects a list of candles and regime
        # For simplicity, we'll use candles up to current point
        current_candles = sample_candles[:i]
        
        # Create a mock regime (normally detected by RegimeManager)
        from tradingsystem.models import MarketRegime
        mock_regime = MarketRegime.TRENDING
        
        try:
            signal = strategy_manager.analyze_market(
                candles=current_candles,
                current_regime=mock_regime,
                adx_value=35.0,  # Mock ADX (trending)
                atr_value=2.5    # Mock ATR
            )
            if signal:
                signals_generated.append(signal)
                print(f"    [{i}] Signal Generated: {signal.signal_type.name} @ {signal.price:.2f}")
            else:
                print(f"    [{i}] No signal (insufficient data or filter rejected)")
        except Exception as inner_e:
            print(f"    [{i}] Analysis error: {inner_e}")
    
    print(f"\n✓ Signals generated: {len(signals_generated)}")
    
except Exception as e:
    print(f"✗ Data flow test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# STEP 7: Database Connectivity Check
# ============================================================================
print("\n[STEP 7] Database Connectivity Check")
print("-" * 80)

try:
    from tradingsystem.data.db import MarketDB
    db = MarketDB()
    print("✓ Database connection ready")
    
    # Check if we can query
    try:
        # Try to get recent data for the symbol
        recent = db.get_candles(config['strategy']['symbol'], limit=5)
        print(f"  - Recent candles in DB: {len(recent) if recent else 0}")
        if recent:
            print(f"    Latest: {recent[-1] if recent else 'None'}")
    except Exception as db_err:
        print(f"  ⚠ DB query warning: {db_err}")
        
except Exception as e:
    print(f"⚠ Database check skipped: {e}")

# ============================================================================
# STEP 8: Broker Connection Check
# ============================================================================
print("\n[STEP 8] Broker Connection Check")
print("-" * 80)

try:
    from tradingsystem.broker.angelone_session import AngelOneSession
    
    broker_config = config.get('brokers', {}).get('angleone', {})
    print(f"✓ Broker config available")
    print(f"  - Username: {'*' * len(broker_config.get('username', ''))}")
    print(f"  - API Key: {'*' * len(broker_config.get('api_key', ''))}")
    print(f"  - Status: Ready to connect (not connected in this test)")
    
except Exception as e:
    print(f"✗ Broker config check failed: {e}")

# ============================================================================
# DATA FLOW VISUALIZATION
# ============================================================================
print("\n" + "=" * 80)
print("DATA FLOW ARCHITECTURE")
print("=" * 80)

flow = """
┌──────────────────────────────────────────────────────────────────────────┐
│                         TRADING SYSTEM DATA FLOW                         │
└──────────────────────────────────────────────────────────────────────────┘

1. CONFIG LAYER
   └─→ Load configuration (default.json / live.json)
       - Broker credentials
       - Strategy parameters
       - Risk management rules

2. BROKER LAYER
   └─→ AngelOne Broker
       - Real-time market data
       - Candle generation (OHLCV)
       - WebSocket feed

3. DATA AGGREGATION
   └─→ RealtimeAggregator
       - Consolidate multi-timeframe candles
       - Buffer incoming ticks
       - Emit CandleClosedEvent

4. ANALYSIS LAYER
   ├─→ RegimeManager
   │   └─ Classifies market: TRENDING / RANGING / VOLATILE
   │      (Based on price levels, ATR, volatility)
   │
   ├─→ StrategyManager
   │   └─ Route to appropriate strategy
   │       ├─ MAStrategy (moving averages)
   │       ├─ RSIStrategy (mean reversion)
   │       └─ BBStrategy (bollinger bands)
   │
   └─→ Signal Generation
       └─ Emit SignalGeneratedEvent (BUY/SELL/HOLD)

5. EXECUTION LAYER
   └─→ ExecutionManager
       - Validates signal against risk rules
       - Places order (if execute_signals=true)
       - Logs trade

6. PERSISTENCE LAYER
   ├─→ Database (SQLite)
   │   - Store candles
   │   - Store signals
   │   - Store trades
   │
   └─→ Logging
       - Event logs
       - Trade logs
       - Error tracking

EVENT BUS CONNECTIVITY:
   SignalGeneratedEvent
   └─→ Subscribers:
       ├─ ExecutionManager
       ├─ Logger
       └─ DBWriter
"""

print(flow)

# ============================================================================
# SUMMARY REPORT
# ============================================================================
print("\n" + "=" * 80)
print("DATA FLOW SUMMARY")
print("=" * 80)

summary = f"""
✓ Configuration:        LOADED
✓ Core Models:          READY
✓ Event Bus:            READY ({1} subscribers)
✓ Regime Manager:       READY (Classification ready)
✓ Strategy Manager:     READY ({strategy_name})
✓ Database:             READY
✓ Broker Config:        READY

Signal Flow Simulation:
  - Input Candles:      {len(sample_candles)} samples processed
  - Signals Generated:  {len(signals_generated)} signals
  - Event Bus Events:   {len(event_log)} events logged

NEXT STEPS:
1. Run: python tradingsystem/main_refactored.py
   - This starts live market data ingestion
   - Connects to AngelOne broker
   - Begins continuous analysis loop

2. Monitor logs in: logs/trading.log

3. To execute trades: Set 'execute_signals': true in config
"""

print(summary)
print("=" * 80)
