"""
DATA FLOW DETAILED ANALYSIS AND TROUBLESHOOTING GUIDE
Comprehensive report of trading system data pathways
"""

import sys
from pathlib import Path
import json
from datetime import datetime

# Add project root
project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print("=" * 90)
print("TRADING SYSTEM - DETAILED DATA FLOW ANALYSIS")
print("=" * 90)
print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ============================================================================
# PART 1: SYSTEM COMPONENTS MAPPING
# ============================================================================
print("\n" + "=" * 90)
print("PART 1: SYSTEM COMPONENTS MAPPING")
print("=" * 90)

components_map = {
    "Configuration Layer": {
        "Files": [
            "tradingsystem/config/default.json",
            "tradingsystem/config/live.json",
            "tradingsystem/config/strategies.json"
        ],
        "Loader": "tradingsystem/config/loader.py",
        "Output": "Dictionary with broker, strategy, and risk configs"
    },
    "Broker Layer": {
        "Provider": "Angel One Broker",
        "Files": [
            "tradingsystem/broker/angelone_session.py",
            "tradingsystem/broker/angelone_fetcher.py",
            "tradingsystem/broker/websocket.py",
            "tradingsystem/broker/order_manager.py"
        ],
        "Input": "Real-time market data",
        "Output": "Candle objects with OHLCV data"
    },
    "Data Aggregation": {
        "Components": [
            "RealtimeAggregator - consolidates ticks into candles",
            "DBWriter - persists to database",
            "MarketDB - query historical data"
        ],
        "Input": "Market ticks from broker",
        "Output": "Closed candles and database records"
    },
    "Analysis Layer": {
        "Regime Detection": {
            "Component": "RegimeManager",
            "Input": "Candles + ADX + ATR indicators",
            "Detection": "TRENDING (ADX > 25) | RANGING (ADX < 20) | VOLATILE (ATR% > 2.5%)",
            "Output": "MarketRegime enum"
        },
        "Strategy Selection": {
            "Component": "StrategyManager",
            "Strategies": [
                "MAStrategy - Trend following via moving average crossover",
                "RSIStrategy - Mean reversion based on RSI levels",
                "BBStrategy - Range trading with Bollinger Bands"
            ],
            "Input": "Candles + Regime + Technical Indicators",
            "Output": "Signal object (BUY/SELL/HOLD)"
        }
    },
    "Execution Layer": {
        "Component": "ExecutionManager",
        "Pre-Execution Checks": [
            "✓ Risk validation (position size, max loss)",
            "✓ Drawdown check (max_daily_loss, max_drawdown_percent)",
            "✓ Account balance verification"
        ],
        "Order Placement": [
            "OrderManager places orders if execute_signals=true",
            "Logs order details to database"
        ],
        "Output": "Order confirmation or skip message"
    },
    "Persistence Layer": {
        "Database": "SQLite with schema for candles, signals, trades",
        "Logging": "Rotating file logs to logs/ directory",
        "Files": [
            "tradingsystem/data/db.py - Database interface",
            "tradingsystem/data/db_writer.py - Async write operations"
        ]
    }
}

for layer, details in components_map.items():
    print(f"\n[{layer}]")
    for key, value in details.items():
        if isinstance(value, list):
            print(f"  {key}:")
            for item in value:
                print(f"    - {item}")
        elif isinstance(value, dict):
            print(f"  {key}:")
            for k, v in value.items():
                print(f"    {k}: {v}")
        else:
            print(f"  {key}: {value}")

# ============================================================================
# PART 2: DATA FLOW PATHS
# ============================================================================
print("\n" + "=" * 90)
print("PART 2: DATA FLOW PATHS (DETAILED)")
print("=" * 90)

flows = {
    "PATH 1: Real-Time Market Data Ingestion": [
        "1. WebSocket connection to AngelOne broker",
        "2. Receive tick updates (price, volume, timestamp)",
        "3. RealtimeAggregator buffers ticks",
        "4. When candle closes → CandleClosedEvent",
        "5. Event published to subscribers",
        "6. DBWriter persists candle to database"
    ],
    "PATH 2: Technical Analysis & Signal Generation": [
        "1. CandleClosedEvent triggers analysis",
        "2. Calculate indicators (MA, RSI, BB, ADX, ATR)",
        "3. RegimeManager.detect_regime() → MarketRegime",
        "4. StrategyManager.analyze_market() → Routes based on regime",
        "5. Selected strategy analyzes candles",
        "6. If criteria met → Generate Signal",
        "7. SignalGeneratedEvent published to event bus"
    ],
    "PATH 3: Signal Execution": [
        "1. ExecutionManager subscribes to SignalGeneratedEvent",
        "2. Validate signal:",
        "   - Check max positions not exceeded",
        "   - Check drawdown limits",
        "   - Check account balance",
        "3. If execute_signals=true:",
        "   - OrderManager.place_order()",
        "   - Returns order_id or error",
        "4. Log to database and files"
    ],
    "PATH 4: Error Handling & Recovery": [
        "1. Connection lost → Automatic reconnect",
        "2. Signal validation fails → Log and skip",
        "3. Order fails → Retry or escalate",
        "4. Database error → Log to file, continue",
        "5. Graceful shutdown on Ctrl+C"
    ]
}

for path, steps in flows.items():
    print(f"\n{path}:")
    for step in steps:
        print(f"  {step}")

# ============================================================================
# PART 3: EVENT FLOW DIAGRAM
# ============================================================================
print("\n" + "=" * 90)
print("PART 3: EVENT FLOW DIAGRAM")
print("=" * 90)

event_flow = """
MARKET TICK (from broker)
        ↓
  RealtimeAggregator (buffers ticks into candles)
        ↓
CANDLE CLOSED (1 minute)
        ↓
  emit CandleClosedEvent
        ↓
    ┌─────────────────────────────────────────────┐
    │  Subscribers listening to CandleClosedEvent │
    └─────────────────────────────────────────────┘
          ↓              ↓              ↓
      [Logger]      [DBWriter]    [Strategy]
          ↓              ↓              ↓
                                 Analyze with indicators
                                        ↓
                                 Detect Regime
                                        ↓
                                 Select Strategy
                                        ↓
                                 Generate Signal?
                                        ↓
                        emit SignalGeneratedEvent
                                        ↓
            ┌──────────────────────────────────────┐
            │ Subscribers to SignalGeneratedEvent   │
            └──────────────────────────────────────┘
              ↓           ↓           ↓           ↓
          [Logger]    [DBWriter]  [Validator]  [Executor]
              ↓           ↓           ↓           ↓
                                   Order?
                                     YES
                                      ↓
                         OrderManager.place_order()
                                      ↓
                              Broker API Call
                                      ↓
                         Order Confirmation/Error
                                      ↓
                              Log result + DB
"""

print(event_flow)

# ============================================================================
# PART 4: DATA TRANSFORMATION STEPS
# ============================================================================
print("\n" + "=" * 90)
print("PART 4: DATA TRANSFORMATION STEPS")
print("=" * 90)

transforms = {
    "Tick → Candle": "RealtimeAggregator aggregates multiple ticks into OHLCV",
    "Candle → Indicators": "Calculate MA, RSI, BB, ADX, ATR from candle history",
    "Indicators → Regime": "RegimeManager classifies into TRENDING/RANGING/VOLATILE",
    "Candle + Regime → Strategy": "StrategyManager selects appropriate strategy",
    "Strategy Analysis → Signal": "Generate BUY/SELL/HOLD based on strategy rules",
    "Signal → Order": "ExecutionManager validates and submits to broker",
    "Order Response → Trade Record": "DBWriter logs to database"
}

for input_type, transform in transforms.items():
    print(f"\n{input_type}")
    print(f"  └─→ {transform}")

# ============================================================================
# PART 5: CONFIGURATION FLOW
# ============================================================================
print("\n" + "=" * 90)
print("PART 5: CONFIGURATION FLOW")
print("=" * 90)

try:
    from tradingsystem.config.loader import load_config
    config = load_config()
    
    print("\nConfiguration Structure:")
    print(json.dumps({
        "system": config.get("system", {}),
        "strategy": config.get("strategy", {}),
        "risk": config.get("risk", {}),
        "brokers.angleone": {
            "username": config.get("brokers", {}).get("angleone", {}).get("username"),
            "exchange": config.get("brokers", {}).get("angleone", {}).get("exchange"),
            "timeframe": config.get("brokers", {}).get("angleone", {}).get("timeframe"),
        }
    }, indent=2))
    
except Exception as e:
    print(f"Error loading config: {e}")

# ============================================================================
# PART 6: TROUBLESHOOTING CHECKLIST
# ============================================================================
print("\n" + "=" * 90)
print("PART 6: TROUBLESHOOTING CHECKLIST")
print("=" * 90)

checklist = {
    "No Signals Generated": [
        "□ Check if strategy has minimum candle history (usually 20+ candles)",
        "□ Verify market regime is correctly detected",
        "□ Check if strategy parameters (fast_ma, slow_ma) are appropriate",
        "□ Ensure sufficient volume to pass min_volume filter",
        "□ Check event_log for strategy analysis details"
    ],
    "Orders Not Executing": [
        "□ Set execute_signals: true in config",
        "□ Check if account has sufficient balance",
        "□ Verify broker connection is active",
        "□ Check if position limit (max_positions) reached",
        "□ Review risk management rules (max_loss_per_trade, max_daily_loss)",
        "□ Check broker order logs for rejection reasons"
    ],
    "Missing Data in Database": [
        "□ Verify database connection in MarketDB",
        "□ Check if DBWriter thread is running",
        "□ Ensure SQLite database file exists and has write permissions",
        "□ Check logs for database errors"
    ],
    "Connection Issues": [
        "□ Verify AngelOne broker credentials in config",
        "□ Check internet connectivity",
        "□ Verify API keys and factor2 authentication",
        "□ Check broker session timeout (should auto-reconnect)",
        "□ Review logs for connection error details"
    ]
}

for issue, checks in checklist.items():
    print(f"\n{issue}:")
    for check in checks:
        print(f"  {check}")

# ============================================================================
# PART 7: PERFORMANCE METRICS
# ============================================================================
print("\n" + "=" * 90)
print("PART 7: KEY PERFORMANCE METRICS TO MONITOR")
print("=" * 90)

metrics = {
    "Data Pipeline": [
        "Candle generation latency (should be < 100ms)",
        "Event bus publish time (should be < 10ms)",
        "Database write time (should be < 50ms)"
    ],
    "Analysis Performance": [
        "Indicator calculation time (ADX, ATR, MA, RSI)",
        "Regime detection latency",
        "Signal generation frequency"
    ],
    "Execution Performance": [
        "Order placement latency (API to broker)",
        "Order confirmation time",
        "Win/Loss ratio",
        "Average trade duration"
    ],
    "System Health": [
        "Memory usage (should remain stable)",
        "Database size growth rate",
        "Number of reconnections (should be minimal)",
        "Error rate (should be < 0.1%)"
    ]
}

for category, metric_list in metrics.items():
    print(f"\n{category}:")
    for metric in metric_list:
        print(f"  • {metric}")

# ============================================================================
# PART 8: QUICK START GUIDE
# ============================================================================
print("\n" + "=" * 90)
print("PART 8: QUICK START GUIDE FOR DATA FLOW VERIFICATION")
print("=" * 90)

startup = """
Step 1: Start the Trading Engine
  $ python tradingsystem/main_refactored.py

Step 2: Verify Initialization
  ✓ Config loaded
  ✓ Broker connected
  ✓ Database ready
  ✓ Strategies loaded

Step 3: Monitor Data Flow
  • Watch for "CandleClosedEvent" messages
  • Check for "Regime detected: TRENDING/RANGING/VOLATILE"
  • Look for "Signal generated: BUY/SELL/HOLD"
  • Verify "Order placed" or "Signal skipped"

Step 4: Check Logs
  $ tail -f logs/trading.log
  
Step 5: Query Results
  • Candles: SELECT COUNT(*) FROM candles;
  • Signals: SELECT COUNT(*) FROM signals;
  • Trades: SELECT COUNT(*) FROM trades;

Step 6: Stop Gracefully
  Press Ctrl+C (should shutdown without errors)
"""

print(startup)

print("\n" + "=" * 90)
print("END OF DETAILED DATA FLOW ANALYSIS")
print("=" * 90)
