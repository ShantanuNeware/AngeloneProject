"""Quick database query to verify strategy data is being saved"""
import sys
from pathlib import Path

project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tradingsystem.data.db import MarketDB

db = MarketDB()

print("=" * 80)
print("STRATEGY DATA - DATABASE VERIFICATION")
print("=" * 80)

# Query recent strategy history
rows = db.fetch_rows("""
    SELECT timestamp, Symbol, Close, Trade_Action, Strategy_State 
    FROM strategy_history 
    ORDER BY timestamp DESC 
    LIMIT 10
""")

print(f"\nRecent strategy data ({len(rows)} rows):")
print("-" * 80)

if rows:
    for i, row in enumerate(rows, 1):
        ts = row.get('timestamp', 'N/A')
        sym = row.get('Symbol', 'N/A')
        close = row.get('Close', 'N/A')
        action = row.get('Trade_Action', 'N/A')
        state = row.get('Strategy_State', 'N/A')
        print(f"{i:2}. {ts} | {sym:15} | Close: {close if isinstance(close, str) else f'{close:8.2f}'} | {action:8} | {state}")
else:
    print("No data found")

# Count statistics
print("\n" + "-" * 80)
print("Database Statistics:")
print("-" * 80)

counts = {
    'strategy_history': db.fetch_rows("SELECT COUNT(*) as cnt FROM strategy_history")[0]['cnt'],
    'signals': db.fetch_rows("SELECT COUNT(*) as cnt FROM signals")[0]['cnt'],
    'candles': db.fetch_rows("SELECT COUNT(*) as cnt FROM candles")[0]['cnt'],
    'indicators': db.fetch_rows("SELECT COUNT(*) as cnt FROM indicators")[0]['cnt'],
}

for table, count in counts.items():
    print(f"  {table:<20}: {count:6} rows")

print("\n" + "=" * 80)
