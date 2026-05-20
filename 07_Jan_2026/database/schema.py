# db/schema.py
from .connection import DBConnection
import logging

logger = logging.getLogger(__name__)

TABLE_SCHEMAS = {
    "historical": {
        "columns": [
            ("datetime", "TEXT PRIMARY KEY"),
            ("date", "TEXT"),
            ("time", "TEXT"),
            ("symbol", "TEXT"),
            ("open", "REAL"),
            ("high", "REAL"),
            ("low", "REAL"),
            ("close", "REAL"),
        ],
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_timestamp ON historical (datetime)"
        ],
    },
    "realtime": {
        "columns": [
            ("timestamp", "TEXT PRIMARY KEY"),
            ("symbol", "TEXT"),
            ("open", "REAL"),
            ("high", "REAL"),
            ("low", "REAL"),
            ("close", "REAL"),
        ],
        "indexes": ["CREATE INDEX IF NOT EXISTS idx_symbol ON realtime (symbol)"],
    },
    "signals": {
        "columns": [
            ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
            ("timestamp", "TEXT"),
            ("symbol", "TEXT"),
            ("action", "TEXT"),
            ("price", "REAL"),
            ("notes", "TEXT"),
        ],
        "indexes": [],
    },
    "price_alerts": {
        "columns": [
            ("id", "INTEGER", "PRIMARY KEY AUTOINCREMENT"),
            ("symbol", "TEXT"),
            ("trigger_price", "REAL"),
            ("direction", "TEXT"),  # ABOVE or BELOW
            ("triggered", "INTEGER"),  # 0 = not triggered, 1 = triggered
            ("timestamp", "TEXT"),
        ],
        "indexes": [],
        "retention_days": 30,
    },
    "pcr_data": {
        "columns": [
            ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
            ("strike", "TEXT"),
            ("symbol_CE", "REAL"),
            ("ltp_CE", "REAL"),
            ("oi_CE", "INTEGER"),
            ("vol_CE", "INTEGER"),
            ("delta_CE", "REAL"),
            ("gamma_CE", "REAL"),
            ("theta_CE", "REAL"),
            ("vega_CE", "REAL"),
            ("signal_CE", "REAL"),
            ("symbol_PE", "REAL"),
            ("ltp_PE", "REAL"),
            ("oi_PE", "INTEGER"),
            ("vol_PE", "INTEGER"),
            ("delta_PE", "REAL"),
            ("gamma_PE", "REAL"),
            ("theta_PE", "REAL"),
            ("vega_PE", "REAL"),
            ("signal_PE", "REAL"),
            ("timestamp", "TEXT"),
            ("pcr", "REAL"),
            ("prediction", "TEXT"),
        ],
        "indexes": [],
    },
    "option_strategy_results": {
        "columns": [
            ("datetime", "TEXT"),
            ("symbol", "TEXT"),
            ("MCG5", "REAL"),
            ("MCG10", "REAL"),
            ("ZLEMA5", "REAL"),
            ("ZLEMA10", "REAL"),
            ("close", "REAL"),
            ("exit_signal", "INTEGER"),
            ("trade_action", "TEXT"),
        ],
        "indexes": [],
        # No retention - manually managed
    },
    "liquidity_pools": {
        "columns": [
            ("timestamp", "TEXT PRIMARY KEY"),
            ("max_ce_oi_strike", "REAL"),
            ("max_pe_oi_strike", "REAL"),
            ("max_ce_vol_strike", "REAL"),
            ("max_pe_vol_strike", "REAL"),
            ("total_ce_oi", "INTEGER"),
            ("total_pe_oi", "INTEGER"),
        ],
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_liquidity_timestamp ON liquidity_pools (timestamp)"
        ],
        "retention_days": 30,
    },
    "strategy_results": {
        "columns": [
            ("DateTime", "TEXT PRIMARY KEY"),  # Assuming DateTime is unique per run/tick? Or maybe not PK?
            # Existing keys expected in strategy_results based on Strategy.py
            ("Trade_Action", "TEXT"),
            ("ml_trade_action", "TEXT"), # Case sensitivity check
            ("cluster_label", "INTEGER"),
            ("cluster_type", "TEXT"),
            ("forecast_next_close", "REAL"),
            ("exit_reason", "TEXT"),
            ("in_trade", "INTEGER"),
            ("trade_direction", "TEXT"),
            ("entry_price", "REAL"),
            
            # New Indicators
            ("KC_Upper", "REAL"),
            ("KC_Lower", "REAL"),
            ("KC_Basis", "REAL"),
            ("Zone", "TEXT"),
            ("UT_Signal", "TEXT"),
            ("TM_Direction", "INTEGER"),
            ("Bulling_Div", "INTEGER"), # Boolean stored as Int
            ("Bearish_Div", "INTEGER"), # Boolean stored as Int
        ],
        "indexes": ["CREATE INDEX IF NOT EXISTS idx_strat_datetime ON strategy_results (DateTime)"],
    },
}


def init_db():
    conn = DBConnection.get_connection()
    with conn:
        for table_name, schema in TABLE_SCHEMAS.items():
            # 1. Create table if not exists
            col_defs = ", ".join([f"{col[0]} {col[1]}" for col in schema["columns"]])
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({col_defs})")

            # 2. Add missing columns (ALTER TABLE)
            cur = conn.execute(f"PRAGMA table_info({table_name})")
            existing_cols = [row[1] for row in cur.fetchall()]

            for col_def in schema["columns"]:
                col_name, col_type = col_def[0], col_def[1]
                if col_name not in existing_cols:
                    alter_query = (
                        f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
                    )
                    try:
                        conn.execute(alter_query)
                        logger.info(f"🆕 Added column '{col_name}' to '{table_name}'")
                    except Exception as e:
                        logger.error(f"❌ Error adding column '{col_name}': {e}")

            for index_sql in schema["indexes"]:
                conn.execute(index_sql)

    logger.info("✅ All DB tables initialized and updated if needed.")
