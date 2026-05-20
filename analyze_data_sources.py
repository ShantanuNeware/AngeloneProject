"""
DATA SOURCE AND DATE RANGE ANALYZER
Identifies where data is being fetched from and what date ranges are being used
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tradingsystem.config.loader import load_config
from tradingsystem.data.db import MarketDB

print("=" * 100)
print("DATA SOURCE AND DATE RANGE ANALYSIS")
print("=" * 100)

# ============================================================================
# SECTION 1: CONFIGURATION - WHERE DATA COMES FROM
# ============================================================================
print("\n[1] DATA SOURCE CONFIGURATION")
print("-" * 100)

config = load_config()

print("\n  Primary Broker (Source of Live Data):")
print("  " + "-" * 96)
broker = config.get('system', {}).get('broker', 'unknown')
print(f"  Broker: {broker.upper()}")

if broker == 'angleone':
    angleone_config = config.get('brokers', {}).get('angleone', {})
    print(f"  Username: {angleone_config.get('username', 'N/A')}")
    print(f"  Exchange: {angleone_config.get('exchange', 'NSE')}")
    print(f"  API Key: {'*' * len(angleone_config.get('api_key', ''))}")
    print(f"  Timeframe: {angleone_config.get('timeframe', '1m')}")

print("\n  Strategy Configuration:")
print("  " + "-" * 96)
strategy_config = config.get('strategy', {})
print(f"  Strategy Name: {strategy_config.get('name', 'unknown')}")
print(f"  Symbol: {strategy_config.get('symbol', 'unknown')}")
print(f"  Exchange: {strategy_config.get('exchange', 'NSE')}")
print(f"  Token: {strategy_config.get('token', 'unknown')}")
print(f"  Timeframe: {strategy_config.get('timeframe', '1h')}")
print(f"  Poll Interval: {strategy_config.get('poll_interval_seconds', 300)} seconds")
print(f"  Data Fetch Minutes: {strategy_config.get('data_fetch_minutes', 60)} minutes")

# ============================================================================
# SECTION 2: CODE-LEVEL DATA FETCH CONFIGURATION
# ============================================================================
print("\n[2] DATA FETCH CONFIGURATION (From Code)")
print("-" * 100)

print("\n  In tradingsystem/main_refactored.py (_fetch_and_process_data method):")
print("  " + "-" * 96)
print("  1. End Date: datetime.now() (Current time)")
print("  2. Start Date: datetime.now() - timedelta(days=30)")
print("  3. Period: 30 DAYS of historical data")
print("  4. Broker: AngelOne")
print("  5. API Method: getCandleData()")
print("  6. Retry Logic: Up to 3 retries with exponential backoff")

print("\n  Data Fetch Flow:")
print("  " + "-" * 96)
fetch_flow = """
  1. TradingEngine._fetch_and_process_data()
     └─ Calculates date range (now - 30 days to now)
     
  2. AngelOneFetcher.fetch()
     └─ Calls: self.client.getCandleData(params)
     └─ Parameters: exchange, symbol_token, interval, fromdate, todate
     
  3. AngelOne API Response
     └─ Returns raw OHLCV candlestick data
     └─ Format: [[timestamp, open, high, low, close, volume], ...]
     
  4. Candle Model Processing
     └─ Converts to Candle objects with typed fields
     
  5. Database Storage
     └─ INSERT INTO candles table
     └─ INSERT INTO strategy_history table
"""
print(fetch_flow)

# ============================================================================
# SECTION 3: DATABASE ANALYSIS - ACTUAL DATA STORED
# ============================================================================
print("\n[3] DATABASE ANALYSIS - ACTUAL DATA STORED")
print("-" * 100)

db = MarketDB()

# Get date range from candles table
try:
    date_info = db.fetch_rows("""
        SELECT 
            COUNT(*) as total_rows,
            MIN(timestamp) as earliest_date,
            MAX(timestamp) as latest_date
        FROM candles
    """)
    
    if date_info and date_info[0]:
        row = date_info[0]
        total = row.get('total_rows', 0)
        earliest = row.get('earliest_date', 'N/A')
        latest = row.get('latest_date', 'N/A')
        
        print(f"\n  Candles Table:")
        print(f"  " + "-" * 96)
        print(f"  Total Records: {total}")
        print(f"  Earliest Date: {earliest}")
        print(f"  Latest Date: {latest}")
        
        if total > 0 and earliest and latest:
            try:
                from datetime import datetime
                earliest_dt = datetime.fromisoformat(earliest.replace('Z', '+00:00')) if isinstance(earliest, str) else earliest
                latest_dt = datetime.fromisoformat(latest.replace('Z', '+00:00')) if isinstance(latest, str) else latest
                diff = (latest_dt - earliest_dt).days
                print(f"  Date Range Span: {diff} days")
            except:
                pass
                
except Exception as e:
    print(f"  Error querying candles: {e}")

# Get date range from strategy_history table
try:
    strategy_info = db.fetch_rows("""
        SELECT 
            COUNT(*) as total_rows,
            MIN(timestamp) as earliest_date,
            MAX(timestamp) as latest_date
        FROM strategy_history
    """)
    
    if strategy_info and strategy_info[0]:
        row = strategy_info[0]
        total = row.get('total_rows', 0)
        earliest = row.get('earliest_date', 'N/A')
        latest = row.get('latest_date', 'N/A')
        
        print(f"\n  Strategy History Table:")
        print(f"  " + "-" * 96)
        print(f"  Total Records: {total}")
        print(f"  Earliest Date: {earliest}")
        print(f"  Latest Date: {latest}")
        
except Exception as e:
    print(f"  Error querying strategy_history: {e}")

# Get symbol distribution
try:
    symbols = db.fetch_rows("SELECT DISTINCT symbol, COUNT(*) as cnt FROM candles GROUP BY symbol ORDER BY cnt DESC")
    
    if symbols:
        print(f"\n  Symbols in Database:")
        print(f"  " + "-" * 96)
        for sym_row in symbols:
            symbol = sym_row.get('symbol', 'unknown')
            count = sym_row.get('cnt', 0)
            print(f"  {symbol:<20}: {count:>6} records")
            
except Exception as e:
    print(f"  Error querying symbols: {e}")

# ============================================================================
# SECTION 4: DATA FETCH SCHEDULE
# ============================================================================
print("\n[4] DATA FETCH SCHEDULE")
print("-" * 100)

print(f"\n  Polling Configuration:")
print(f"  " + "-" * 96)
poll_interval = strategy_config.get('poll_interval_seconds', 300)
print(f"  Poll Interval: {poll_interval} seconds ({poll_interval/60:.1f} minutes)")
print(f"  Expected Fetches per Hour: {3600 / poll_interval:.0f}")
print(f"  Expected Fetches per Day: {86400 / poll_interval:.0f}")

print(f"\n  Data Fetch Behavior:")
print(f"  " + "-" * 96)
print(f"  1. Every {poll_interval} seconds:")
print(f"     - Check if enough time has passed since last fetch")
print(f"     - Fetch 30 days of data from AngelOne broker")
print(f"     - Process and store new candles")
print(f"     - Analyze and generate signals")
print(f"\n  2. Continuous Loop:")
print(f"     - Data fetching is continuous and real-time")
print(f"     - Each fetch gets the latest 30 days")
print(f"     - New candles are appended to database")
print(f"     - Strategy analysis happens on each new candle")

# ============================================================================
# SECTION 5: DATA PERSISTENCE FLOW
# ============================================================================
print("\n[5] DATA PERSISTENCE FLOW")
print("-" * 100)

flow = """
  AngelOne Broker API
  │
  ├─ Sends: OHLCV data for last 30 days
  │
  ↓ (via AngelOneFetcher.fetch())
  
  TradingEngine._fetch_and_process_data()
  │
  ├─ Parses raw data into Candle objects
  │ (symbol, timestamp, open, high, low, close, volume, timeframe)
  │
  ↓
  
  Database (SQLite - trading_v4.db)
  │
  ├─ INSERT INTO candles (timestamp, open, high, low, close, volume, ...)
  ├─ INSERT INTO realtime (same fields as candles)
  │
  ↓
  
  Strategy Analysis
  │
  ├─ RegimeManager analyzes price trends
  ├─ StrategyManager runs selected strategy (MA, RSI, BB)
  │ 
  ↓
  
  Signal Generation
  │
  ├─ If signal generated: INSERT INTO strategy_history
  │ (timestamp, Symbol, Close, Trade_Action, Strategy_State, ...)
  │
  ↓
  
  Database (Final Storage)
  
  Tables Updated:
  - candles (Raw market data)
  - realtime (Real-time copy)
  - strategy_history (Trading signals)
  - indicators (Calculated indicators)
"""

print(flow)

# ============================================================================
# SECTION 6: TIME ZONES AND TIMESTAMPS
# ============================================================================
print("\n[6] TIME ZONES AND TIMESTAMPS")
print("-" * 100)

print(f"\n  Current System Time: {datetime.now()}")
print(f"  Current ISO Format: {datetime.now().isoformat()}")

print(f"\n  Data Fetch Date Calculation:")
print(f"  " + "-" * 96)
end_time = datetime.now()
start_time = end_time - timedelta(days=30)
print(f"  End (Fetch Until): {end_time.isoformat()}")
print(f"  Start (Fetch From): {start_time.isoformat()}")
print(f"  Period: 30 days")

print(f"\n  Angel One API Format:")
print(f"  " + "-" * 96)
print(f"  fromdate: {start_time.strftime('%Y-%m-%d %H:%M')}")
print(f"  todate: {end_time.strftime('%Y-%m-%d %H:%M')}")

# ============================================================================
# SECTION 7: CONFIGURABLE PARAMETERS
# ============================================================================
print("\n[7] CONFIGURABLE PARAMETERS (In config/default.json)")
print("-" * 100)

print("\n  Can be Modified:")
print(f"  " + "-" * 96)
print(f"  'poll_interval_seconds': {poll_interval}")
print(f"    └─ How often to fetch data (default: 300s = 5 minutes)")
print(f"\n  'data_fetch_minutes': {strategy_config.get('data_fetch_minutes', 60)}")
print(f"    └─ Data window in minutes (default: 60)")
print(f"\n  'timeframe': '{strategy_config.get('timeframe', '1h')}'")
print(f"    └─ Candle timeframe (1m, 5m, 15m, 1h, 4h, 1d)")

# ============================================================================
# SECTION 8: DATA SOURCES SUMMARY
# ============================================================================
print("\n[8] COMPLETE DATA FLOW SUMMARY")
print("-" * 100)

summary = f"""
┌─────────────────────────────────────────────────────────────────────────┐
│                          DATA SOURCE CHAIN                              │
└─────────────────────────────────────────────────────────────────────────┘

SOURCE:        AngelOne Broker (Angel Broking Limited)
│
├─ Authentication: {angleone_config.get('username', 'N/A')}
├─ Credentials: API Key + Factor2 (OTP) authentication
├─ Broker Exchange: NSE (National Stock Exchange - India)
│
↓ (Every {poll_interval} seconds)

FETCHER:       AngelOneFetcher.fetch()
│
├─ Method: getCandleData()
├─ Token: NIFTY (99926000) or Symbol Token from config
├─ Interval: {strategy_config.get('timeframe', '1h')} timeframe
├─ Date Range: Last 30 days (sliding window)
├─ From: {start_time.strftime('%Y-%m-%d %H:%M')}
├─ To: {end_time.strftime('%Y-%m-%d %H:%M')}
│
↓

PROCESSING:    TradingEngine._fetch_and_process_data()
│
├─ Parse OHLCV data into Candle objects
├─ Validate timestamp and price data
├─ Handle API errors with retry logic (3 retries)
│
↓

DATABASE:      SQLite (trading_v4.db)
│
├─ Table: candles
│   └─ Stores raw OHLCV data
│   └─ Current: {total if 'total' in locals() else '?'} records
│
├─ Table: strategy_history
│   └─ Stores generated trading signals
│   └─ Stores regime and strategy state
│
└─ Table: indicators
    └─ Stores calculated technical indicators


DATE RANGES CURRENTLY IN DATABASE:
├─ Earliest: {earliest if 'earliest' in locals() else 'N/A'}
├─ Latest: {latest if 'latest' in locals() else 'N/A'}
└─ Span: Records stored for comparison and backtesting

"""

print(summary)

# ============================================================================
# SECTION 9: QUICK REFERENCE
# ============================================================================
print("\n[9] QUICK REFERENCE")
print("-" * 100)

print("""
  Where is data from?
  └─ AngelOne Broker (Indian stock market data)
  
  What dates are being fetched?
  └─ Rolling 30-day window (previous 30 days to now)
  
  What dates are in the database?
  └─ All data fetched since the system started running
  
  How often is data fetched?
  └─ Every 300 seconds (5 minutes) by default
  
  What happens with the data?
  └─ Stored in candles table → analyzed by strategies
     → signals generated → stored in strategy_history
  
  Can I change the date range?
  └─ Yes - modify main_refactored.py line 235
     Change: start = end - timedelta(days=30)
     To: start = end - timedelta(days=N)  # Where N = days you want
     
  Can I change the fetch interval?
  └─ Yes - modify config/default.json
     Change: "poll_interval_seconds": 300
     To: "poll_interval_seconds": N  # Where N = seconds between fetches
""")

print("\n" + "=" * 100)
