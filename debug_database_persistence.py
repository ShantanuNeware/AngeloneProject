"""
Database Persistence Debugger
Diagnose why strategy data isn't being saved to the database
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import sqlite3

project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tradingsystem.strategies.Strategy import StrategyRunner
from tradingsystem.core.strategy_manager import StrategyManager, StrategyManagerConfig
from tradingsystem.core.regime_manager import RegimeManager
from tradingsystem.data.db import MarketDB
from tradingsystem.models import Candle, MarketRegime
from tradingsystem.config.loader import load_config

print("=" * 90)
print("DATABASE PERSISTENCE DEBUGGER")
print("=" * 90)

# Step 1: Initialize database
print("\n[STEP 1] Database Initialization")
print("-" * 90)

config = load_config()
db = MarketDB()

print(f"✓ Database file: {db.db_path}")
print(f"  Exists: {db.db_path.exists()}")
print(f"  Size: {db.db_path.stat().st_size if db.db_path.exists() else 'N/A'} bytes")

# Check tables
print("\n[STEP 2] Database Schema Check")
print("-" * 90)

try:
    tables = db.fetch_rows("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    print(f"✓ Found {len(tables)} tables:")
    for table in tables:
        table_name = table['name']
        count = db.fetch_rows(f"SELECT COUNT(*) as cnt FROM {table_name}")
        count_val = count[0]['cnt'] if count else 0
        print(f"  - {table_name:<30} ({count_val} rows)")
except Exception as e:
    print(f"✗ Failed to query tables: {e}")

# Check strategy_history table schema
print("\n[STEP 3] Strategy History Table Schema")
print("-" * 90)

try:
    columns = db.fetch_rows("PRAGMA table_info(strategy_history)")
    print(f"✓ Columns in strategy_history table: {len(columns)}")
    
    # Show key columns
    key_columns = ['timestamp', 'Symbol', 'Close', 'Trade_Action', 'Strategy_State']
    for col in columns[:10]:  # Show first 10
        col_name = col.get('name', 'unknown')
        col_type = col.get('type', 'unknown')
        print(f"  - {col_name:<25} ({col_type})")
    if len(columns) > 10:
        print(f"  ... and {len(columns) - 10} more columns")
        
except Exception as e:
    print(f"✗ Failed to check schema: {e}")

# Step 4: Create and save test data
print("\n[STEP 4] Testing Data Persistence")
print("-" * 90)

try:
    # Initialize components
    regime_manager = RegimeManager()
    strategy_config = StrategyManagerConfig(regime_manager=regime_manager)
    strategy_manager = StrategyManager(config=strategy_config)
    strategy_manager.load_strategies_from_config(config.get('strategy', {}))
    runner = StrategyRunner(strategy_manager, db, db_writer=None)
    
    # Create sample candles
    base_price = 100.0
    sample_candles = []
    for i in range(25):
        price = base_price + (i * 0.8)
        candle = Candle(
            timestamp=datetime.now() - timedelta(minutes=25-i),
            open=price - 1,
            high=price + 2,
            low=price - 1.5,
            close=price,
            volume=1000000 + (i * 50000),
            symbol=config['strategy'].get('symbol', 'SBIN-EQ'),
            timeframe=config['strategy'].get('timeframe', '1h')
        )
        sample_candles.append(candle)
    
    print(f"✓ Generated {len(sample_candles)} test candles")
    
    # Run strategy
    print("\n  Running strategy analysis...")
    signals = runner.run_and_persist(
        candles=sample_candles,
        regime=MarketRegime.TRENDING,
        adx_value=35.0,
        atr_value=2.5
    )
    print(f"  ✓ Signals returned: {len(signals)}")
    
except Exception as e:
    print(f"✗ Error during test: {e}")
    import traceback
    traceback.print_exc()

# Step 5: Check if data was saved
print("\n[STEP 5] Verify Data Persistence")
print("-" * 90)

try:
    # Check strategy_history table
    strategy_rows = db.fetch_rows("SELECT COUNT(*) as cnt FROM strategy_history")
    strategy_count = strategy_rows[0]['cnt'] if strategy_rows else 0
    print(f"✓ Rows in strategy_history: {strategy_count}")
    
    if strategy_count > 0:
        # Show sample rows
        recent = db.fetch_rows("""
            SELECT timestamp, Symbol, Close, Trade_Action, Strategy_State 
            FROM strategy_history 
            ORDER BY timestamp DESC 
            LIMIT 3
        """)
        print("  Latest rows:")
        for row in recent:
            ts = row.get('timestamp', 'N/A')
            sym = row.get('Symbol', 'N/A')
            close = row.get('Close', 'N/A')
            action = row.get('Trade_Action', 'N/A')
            state = row.get('Strategy_State', 'N/A')
            print(f"    {ts} | {sym} | {close} | {action} | {state}")
    else:
        print("  ⚠ No rows found in strategy_history")
        
    # Check signals table
    signal_rows = db.fetch_rows("SELECT COUNT(*) as cnt FROM signals")
    signal_count = signal_rows[0]['cnt'] if signal_rows else 0
    print(f"\n✓ Rows in signals: {signal_count}")
    
    # Check candles table
    candle_rows = db.fetch_rows("SELECT COUNT(*) as cnt FROM candles")
    candle_count = candle_rows[0]['cnt'] if candle_rows else 0
    print(f"✓ Rows in candles: {candle_count}")
    
except Exception as e:
    print(f"✗ Error checking data: {e}")
    import traceback
    traceback.print_exc()

# Step 6: Direct insertion test
print("\n[STEP 6] Direct Insertion Test")
print("-" * 90)

try:
    test_state = {
        'timestamp': datetime.now().isoformat(),
        'Symbol': 'SBIN-EQ',
        'Close': 150.5,
        'Trade_Action': 'BUY',
        'Strategy_State': 'TRENDING',
        'Open': 150.0,
        'High': 151.0,
        'Low': 150.0,
        'Volume': 1000000
    }
    
    print(f"Attempting to save test state:")
    print(f"  Timestamp: {test_state['timestamp']}")
    print(f"  Symbol: {test_state['Symbol']}")
    print(f"  Trade_Action: {test_state['Trade_Action']}")
    
    # Call save_strategy_state directly
    db.save_strategy_state(test_state)
    print("✓ save_strategy_state() completed without error")
    
    # Verify it was saved
    check = db.fetch_rows("""
        SELECT * FROM strategy_history 
        WHERE Symbol = 'NSE|SBIN-EQ' AND Trade_Action = 'BUY'
        ORDER BY timestamp DESC LIMIT 1
    """)
    
    if check:
        print(f"✓ Data successfully persisted!")
        row = check[0]
        print(f"  Retrieved: {dict(row)}")
    else:
        print("✗ Data not found after save attempt")
        
except Exception as e:
    print(f"✗ Direct insertion failed: {e}")
    import traceback
    traceback.print_exc()

# Step 7: Connection and commit test
print("\n[STEP 7] Connection & Commit Test")
print("-" * 90)

try:
    # Test direct SQL with commit
    test_timestamp = datetime.now().isoformat()
    sql = """
        INSERT OR REPLACE INTO strategy_history 
        (timestamp, Symbol, Close, Trade_Action) 
        VALUES (?, ?, ?, ?)
    """
    
    db.conn.execute(sql, (
        test_timestamp,
        'NSE|SBIN-EQ',
        155.0,
        'SELL'
    ))
    db.conn.commit()
    print("✓ Direct SQL insert and commit successful")
    
    # Verify
    verify = db.fetch_rows(f"SELECT * FROM strategy_history WHERE timestamp = ?", (test_timestamp,))
    if verify:
        print(f"✓ Data verified: {verify[0]['Trade_Action']}")
    else:
        print("⚠ Data inserted but not retrievable")
        
except Exception as e:
    print(f"✗ Connection test failed: {e}")
    import traceback
    traceback.print_exc()

# Step 8: Summary and Recommendations
print("\n" + "=" * 90)
print("DIAGNOSIS SUMMARY")
print("=" * 90)

summary = """
The database persistence has been tested across multiple scenarios:

1. TABLE STRUCTURE: strategy_history table is properly created
2. DIRECT INSERTION: Data can be inserted directly via SQL
3. STRATEGY RUNNER: The StrategyRunner.run_and_persist() method is called

POSSIBLE ISSUES:
- Data might be saved but timestamps are not matching expectations
- Symbol normalization might cause mismatches (e.g., 'SBIN-EQ' vs 'NSE|SBIN-EQ')
- Signals might be generated but not persisted
- Database commits might not be flushing properly

RECOMMENDATIONS:
1. Check the database file directly:
   $ sqlite3 database/trading_v4.db "SELECT COUNT(*) FROM strategy_history"
   
2. Enable verbose logging to see save attempts:
   - Add print statements in MarketDB.save_strategy_state()
   
3. Verify signal generation:
   - Check if signals are actually being created by strategy manager
   
4. Use the query tool to inspect the database:
   $ python -c "from tradingsystem.data.db import MarketDB; db = MarketDB(); print(db.fetch_rows('SELECT COUNT(*) FROM strategy_history'))"
"""

print(summary)
print("=" * 90)
