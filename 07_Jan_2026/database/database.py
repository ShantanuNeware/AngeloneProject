import sqlite3
import pandas as pd
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import smtplib
import json
from email.message import EmailMessage
from pushbullet import Pushbullet
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import logging
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TradingDB:
    _instance = None
    _lock = threading.Lock()
    DB_VERSION = 3  # Increment when schema changes
    DEFAULT_RETENTION_DAYS = 1  # Default data retention period

    # Define the current schema for all tables
    TABLE_SCHEMAS = {
        "option_monitor_results": {
            "columns": [
                ("id", "INTEGER", "PRIMARY KEY AUTOINCREMENT"),
                ("datetime", "TEXT"),
                ("symbol", "TEXT"),
                ("indicators", "TEXT"),  # JSON string of indicator values
                ("is_exit", "INTEGER"),  # Boolean as integer
                ("exit_reason", "TEXT"),
                ("trade_direction", "TEXT"),
                ("entry_price", "REAL"),
            ],
            "indexes": [
                "CREATE INDEX IF NOT EXISTS idx_option_monitor_datetime ON option_monitor_results (datetime)",
                "CREATE INDEX IF NOT EXISTS idx_option_monitor_symbol ON option_monitor_results (symbol)",
            ],
            "retention_days": 30,  # Keep option monitor data for 1 month
        },
        "historical": {
            "columns": [
                ("datetime", "TEXT", "PRIMARY KEY"),
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
            # No retention - manually managed
        },
        "realtime": {
            "columns": [
                ("timestamp", "TEXT", "PRIMARY KEY"),
                ("symbol", "TEXT"),
                ("open", "REAL"),
                ("high", "REAL"),
                ("low", "REAL"),
                ("close", "REAL"),
            ],
            "indexes": ["CREATE INDEX IF NOT EXISTS idx_symbol ON realtime (symbol)"],
            "retention_days": 30,  # Keep realtime data for 1 month
        },
        "signals": {
            "columns": [
                ("id", "INTEGER", "PRIMARY KEY AUTOINCREMENT"),
                ("timestamp", "TEXT"),
                ("symbol", "TEXT"),
                ("action", "TEXT"),
                ("price", "REAL"),
                ("notes", "TEXT"),
            ],
            "indexes": [],
            "retention_days": 30,  # Keep signals for 1 month
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
                ("id", "INTEGER", "PRIMARY KEY AUTOINCREMENT"),
                ("strike", "TEXT"),
                ("symbol_CE", "TEXT"),
                ("ltp_CE", "REAL"),
                ("oi_CE", "INTEGER"),
                ("vol_CE", "INTEGER"),
                ("delta_CE", "REAL"),
                ("gamma_CE", "REAL"),
                ("theta_CE", "REAL"),
                ("vega_CE", "REAL"),
                ("signal_CE", "REAL"),
                ("symbol_PE", "TEXT"),
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
            "retention_days": 30,  # Keep PCR data for 1 month
        },
        "trade_data": {
            "columns": [
                ("id", "INTEGER", "PRIMARY KEY AUTOINCREMENT"),
                ("timestamp", "TEXT"),
                ("symbol", "TEXT"),
                ("action", "TEXT"),
                ("price", "REAL"),
                ("qty", "INTEGER"),  # Number of units/lots traded
                ("mode", "TEXT"),  # TEST or LIVE trade
                ("notes", "TEXT"),
            ],
            "indexes": [
                "CREATE INDEX IF NOT EXISTS idx_mock_trades_timestamp ON trade_data (timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_mock_trades_symbol ON trade_data (symbol)",
            ],
            "retention_days": 1,
        },
        "option_historical": {
            "columns": [
                ("datetime", "TEXT"),
                ("symbol", "TEXT"),
                ("Open", "REAL"),
                ("High", "REAL"),
                ("Low", "REAL"),
                ("Close", "REAL"),
                ("Volume", "REAL"),
                ("MCG5", "REAL"),  # New column for MCG5
                ("MCG14", "REAL"),  # New column for MCG14
                ("ZLEMA7", "REAL"),  # New column for ZLEMA7
                ("ZLEMA21", "REAL"),  # New column for ZLEMA21
            ],
            "indexes": [],
            # No retention - manually managed
        },
        "strategy_results": {
            "columns": [
                ("datetime", "TEXT"),
                ("symbol", "TEXT"),
                ("MCG5", "REAL"),
                ("MCG10", "REAL"),
                ("ZLEMA5", "REAL"),
                ("ZLEMA10", "REAL"),
                ("close", "REAL"),
                ("STARC_MA", "REAL"),
                ("STARC_Band_Up", "REAL"),
                ("STARC_Band_Dn", "REAL"),
                ("exit_signal", "INTEGER"),
            ],
            "indexes": [],
            # No retention - manually managed
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
    }

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.conn = sqlite3.connect(
                        "database/trading.db", check_same_thread=False, timeout=30
                    )
                    # Lock to serialize write transactions across threads
                    cls._instance._write_lock = threading.Lock()
                    cls._instance._init_db()
                    # cls._instance.pb = Pushbullet("YOUR_API_KEY")  # Uncomment for push notifications

                    # Perform initial cleanup on startup
                    cls._instance.cleanup_old_data()
        return cls._instance

    def _init_db(self):
        with self.conn:
            # Enable WAL mode for better concurrency
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA cache_size=-10000")  # 10MB cache

            # Create version table if not exists
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS db_version (version INTEGER PRIMARY KEY)"
            )

            # Get current version
            version_result = self.conn.execute(
                "SELECT version FROM db_version ORDER BY version DESC LIMIT 1"
            ).fetchone()
            current_version = version_result[0] if version_result else 0

            # Migrate if needed
            if current_version < self.DB_VERSION:
                self._migrate_db(current_version)

            # Ensure all tables are up-to-date
            for table_name, schema in self.TABLE_SCHEMAS.items():
                self._ensure_table_schema(table_name, schema["columns"])

                # Create indexes
                for index_sql in schema["indexes"]:
                    try:
                        self.conn.execute(index_sql)
                    except sqlite3.OperationalError:
                        logger.warning(f"Index already exists: {index_sql}")

    def _migrate_db(self, current_version: int):
        """Perform database migrations incrementally"""
        logger.info(
            f"Migrating database from version {current_version} to {self.DB_VERSION}"
        )

        with self.conn:
            # Version 1 to 2 migration
            if current_version < 1:
                # Initial migration - ensure all tables are created
                for table_name, schema in self.TABLE_SCHEMAS.items():
                    self._ensure_table_schema(table_name, schema["columns"])

            # Version 2 to 3 migration
            if current_version < 2:
                # Add any new columns to existing tables
                for table_name, schema in self.TABLE_SCHEMAS.items():
                    self._migrate_table_columns(table_name, schema["columns"])

            # Update version
            self.conn.execute(
                "INSERT OR REPLACE INTO db_version (rowid, version) VALUES (1, ?)",
                (self.DB_VERSION,),
            )

        logger.info(f"Database migrated to version {self.DB_VERSION}")

    def _ensure_table_schema(self, table_name: str, columns: List[tuple]):
        """Ensure table exists with correct schema"""
        # Check if table exists
        table_exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()

        if not table_exists:
            # Create new table
            self._create_table(table_name, columns)
            return

        # Verify existing table structure
        existing_columns = self._get_table_columns(table_name)
        required_columns = [col[0] for col in columns]

        # Check for missing columns
        missing_columns = [
            col for col in required_columns if col not in existing_columns
        ]

        if missing_columns:
            self._migrate_table_columns(table_name, columns)

    def _migrate_table_columns(self, table_name: str, columns: List[tuple]):
        """Migrate table to add missing columns"""
        existing_columns = self._get_table_columns(table_name)
        required_columns = [col[0] for col in columns]

        # Add missing columns
        for col_def in columns:
            col_name = col_def[0]
            if col_name not in existing_columns:
                logger.info(f"Adding column {col_name} to {table_name}")
                try:
                    self.conn.execute(
                        f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def[1]}"
                    )
                except sqlite3.OperationalError as e:
                    logger.error(f"Failed to add column {col_name}: {str(e)}")

    def _get_table_columns(self, table_name: str) -> List[str]:
        """Get list of columns in a table"""
        cursor = self.conn.execute(f"PRAGMA table_info({table_name})")
        return [row[1] for row in cursor.fetchall()]

    def _create_table(self, table_name: str, columns: List[tuple]):
        """Create new table with specified schema"""
        logger.info(f"Creating new table: {table_name}")

        # Build column definitions
        col_defs = []
        for col in columns:
            col_def = f"{col[0]} {col[1]}"
            if len(col) > 2:  # Has constraints
                col_def += f" {col[2]}"
            col_defs.append(col_def)

        create_sql = f"""
            CREATE TABLE {table_name} (
                {', '.join(col_defs)}
            )
        """
        self.conn.execute(create_sql)

    def cleanup_old_data(self):
        """Automatically purge old data from all tables at startup"""
        logger.info("Performing initial data cleanup...")

        for table_name, schema in self.TABLE_SCHEMAS.items():
            retention_days = schema.get("retention_days", self.DEFAULT_RETENTION_DAYS)

            if retention_days <= 0:
                logger.info(f"Skipping cleanup for {table_name} (retention disabled)")
                continue

            # Preferred time column based on table type
            preferred = (
                "datetime"
                if table_name
                in ("historical", "option_historical", "option_strategy_results")
                else "timestamp"
            )

            # Get actual columns in the table and pick an available time column
            existing_cols = self._get_table_columns(table_name)
            if preferred in existing_cols:
                time_column = preferred
            else:
                alt = "datetime" if preferred == "datetime" else "DateTime"
                if alt in existing_cols:
                    time_column = alt
                    logger.info(
                        f"Using alternate time column '{alt}' for cleanup of table '{table_name}'"
                    )
                else:
                    logger.warning(
                        f"No time column ('{preferred}' or '{alt}') found in {table_name}; skipping cleanup."
                    )
                    continue

            # Calculate cutoff date
            cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

            with self._write_lock:
                with self.conn:
                    try:
                        # Execute deletion
                        self.conn.execute(
                            f"DELETE FROM {table_name} WHERE {time_column} < ?",
                            (cutoff,),
                        )
                        deleted_rows = self.conn.total_changes
                    except sqlite3.OperationalError as e:
                        logger.error(
                            f"Cleanup failed for {table_name} using column {time_column}: {e}"
                        )
                        continue

            logger.info(
                f"Purged {deleted_rows} rows from {table_name} (older than {retention_days} days)"
            )

    def insert_signal(self, signal: dict):
        """Insert trading signal"""
        with self._write_lock:
            with self.conn:
                self.conn.execute(
                    """
                INSERT INTO signals (timestamp, symbol, action, price, notes)
                VALUES (?,?,?,?,?)
                """,
                    (
                        signal.get("timestamp", datetime.now().isoformat()),
                        signal["symbol"],
                        signal["action"],
                        signal["price"],
                        signal.get("notes", ""),
                    ),
                )
            # self.send_push_notification("New Signal", f"{signal['symbol']} {signal['action']} at {signal['price']}")  # Uncomment for push notifications

    def get_candles(self, symbol: str, limit: int = 100) -> pd.DataFrame:
        """Get recent candles for symbol"""
        return pd.read_sql(
            f"""
        SELECT * FROM realtime 
        WHERE symbol = '{symbol}'
        ORDER BY timestamp DESC
        LIMIT {limit}
        """,
            self.conn,
        )

    def get_signals(self, hours: int = 24) -> pd.DataFrame:
        """Get recent signals"""
        return pd.read_sql(
            f"""
        SELECT * FROM signals
        WHERE timestamp > datetime('now', '-{hours} hours')
        ORDER BY timestamp DESC
        """,
            self.conn,
        )

    def generate_plot(self, symbol: str, hours: int = 6) -> str:
        """Generate price plot as base64"""
        df = pd.read_sql(
            f"""
        SELECT timestamp, close FROM realtime
        WHERE symbol = '{symbol}'
          AND timestamp > datetime('now', '-{hours} hours')
        ORDER BY timestamp
        """,
            self.conn,
        )

        plt.figure(figsize=(10, 4))
        plt.plot(df["timestamp"], df["close"])
        plt.title(f"{symbol} Price - Last {hours} Hours")
        plt.xticks(rotation=45)
        plt.tight_layout()

        img = BytesIO()
        plt.savefig(img, format="png", dpi=80)
        plt.close()
        img.seek(0)
        return base64.b64encode(img.getvalue()).decode()

    def send_email_alert(self, subject: str, body: str):
        """Send email alert"""
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = "alerts@yourdomain.com"
        msg["To"] = "your@email.com"

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login("your@email.com", "password")
            server.send_message(msg)

    def send_push_notification(self, title: str, body: str):
        """Send mobile push notification"""
        self.pb.push_note(title, body)

    def close(self):
        """Cleanup database connections"""
        self.conn.close()

    def clear_all_tables(self):
        """Delete all rows from all tables (use with caution)"""
        with self._write_lock:
            with self.conn:
                for table_name in self.TABLE_SCHEMAS.keys():
                    self.conn.execute(f"DELETE FROM {table_name}")
                    logger.info(f"🧹 Cleared table: {table_name}")

    def insert_historical(self, df: pd.DataFrame):
        """Insert historical candle data"""
        if df.empty:
            return

        df = df.rename(
            columns={
                "DateTime": "datetime",
                "Date": "date",
                "Time": "time",
                "Symbol": "symbol",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
            }
        )
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.drop_duplicates(subset=["datetime"], keep="last")

        with self.conn:
            for _, row in df.iterrows():
                try:
                    self.conn.execute(
                        """
                        INSERT OR IGNORE INTO historical (datetime, date, time, symbol, open, high, low, close) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            row["datetime"].isoformat(),
                            row["date"],
                            row["time"],
                            row["symbol"],
                            row["open"],
                            row["high"],
                            row["low"],
                            row["close"],
                        ),
                    )
                except Exception as e:
                    logger.error(f"❌ Failed to insert row: {e}")
        logger.info(f"✅ Inserted {len(df)} historical rows")

    def insert_option_historical(self, df: pd.DataFrame):
        """Insert historical candle data"""
        if df.empty:
            return

        df = df.rename(
            columns={
                "DateTime": "datetime",
                "Date": "date",
                "Time": "time",
                "Symbol": "symbol",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
            }
        )
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.drop_duplicates(subset=["datetime"], keep="last")

        with self.conn:
            for _, row in df.iterrows():
                try:
                    self.conn.execute(
                        """
                        INSERT OR IGNORE INTO option_historical (datetime, date, time, symbol, open, high, low, close) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            row["datetime"].isoformat(),
                            row["date"],
                            row["time"],
                            row["symbol"],
                            row["open"],
                            row["high"],
                            row["low"],
                            row["close"],
                        ),
                    )
                except Exception as e:
                    logger.error(f"❌ Failed to insert row: {e}")
        logger.info(f"✅ Inserted {len(df)} historical rows")

    def insert_realtime(self, data: dict):
        """Insert real-time tick data

        Accepts dicts that may use either 'timestamp' or 'datetime' as the time key.
        """
        if data.get("close") == 0:
            logger.debug("Ignoring zero LTP tick")
            return

        ts = data.get("timestamp") or data.get("datetime")

        with self._write_lock:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO realtime (timestamp, symbol, open, high, low, close) 
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        ts,
                        data["symbol"],
                        data["open"],
                        data["high"],
                        data["low"],
                        data["close"],
                    ),
                )

    def insert_liquidity_pool(self, data: dict):
        """Insert liquidity pool data"""
        with self._write_lock:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO liquidity_pools (
                        timestamp, max_ce_oi_strike, max_pe_oi_strike, 
                        max_ce_vol_strike, max_pe_vol_strike, 
                        total_ce_oi, total_pe_oi
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data.get("timestamp", datetime.now().isoformat()),
                        data.get("max_ce_oi_strike"),
                        data.get("max_pe_oi_strike"),
                        data.get("max_ce_vol_strike"),
                        data.get("max_pe_vol_strike"),
                        data.get("total_ce_oi"),
                        data.get("total_pe_oi"),
                    ),
                )

    def insert_pcr(self, pcr: float, prediction: str, timestamp: str, rows: list):
        """Insert PCR data"""

        def scalar(x):
            return x.values[0] if isinstance(x, pd.Series) else x

        if timestamp is None:
            timestamp = datetime.now().isoformat()

        with self._write_lock:
            with self.conn:
                for row in rows:
                    strike_val = scalar(row["strike"])

                    self.conn.execute(
                        """
                        INSERT INTO pcr_data (
                            timestamp, strike,
                            symbol_CE, ltp_CE, oi_CE, vol_CE, delta_CE, gamma_CE, theta_CE, vega_CE, signal_CE,
                            symbol_PE, ltp_PE, oi_PE, vol_PE, delta_PE, gamma_PE, theta_PE, vega_PE, signal_PE,
                            pcr, prediction
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            timestamp,
                            strike_val,
                            scalar(row.get("symbol_CE")),
                            float(scalar(row.get("ltp_CE", 0))),
                            int(scalar(row.get("oi_CE", 0))),
                            int(scalar(row.get("vol_CE", 0))),
                            float(scalar(row.get("delta_CE", 0))),
                            float(scalar(row.get("gamma_CE", 0))),
                            float(scalar(row.get("theta_CE", 0))),
                            float(scalar(row.get("vega_CE", 0))),
                            scalar(row.get("signal_CE")),
                            scalar(row.get("symbol_PE")),
                            float(scalar(row.get("ltp_PE", 0))),
                            int(scalar(row.get("oi_PE", 0))),
                            int(scalar(row.get("vol_PE", 0))),
                            float(scalar(row.get("delta_PE", 0))),
                            float(scalar(row.get("gamma_PE", 0))),
                            float(scalar(row.get("theta_PE", 0))),
                            float(scalar(row.get("vega_PE", 0))),
                            scalar(row.get("signal_PE")),
                            float(pcr),
                            prediction,
                        ),
                    )

    def insert_trade_data(self, trade):
        """Insert trade execution data"""
        with self._write_lock:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO trade_data (timestamp, symbol, action, price, qty, mode, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade.get("timestamp"),
                        trade.get("symbol"),
                        trade.get("action"),
                        trade.get("price"),
                        trade.get("qty"),
                        trade.get("mode", "TEST"),
                        trade.get("notes", ""),
                    ),
                )

    def create_option_table(self, option_symbol):
        """
        Create a table for a specific option symbol if it does not exist.
        Table name will be sanitized.
        """
        table_name = (
            f"option_{''.join(c if c.isalnum() else '_' for c in option_symbol)}"
        )
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            source TEXT
        );
        """
        try:
            with self._write_lock:
                self.conn.execute(create_sql)
                self.conn.commit()
            logging.info(f"Table created or exists: {table_name}")
        except Exception as e:
            logging.error(f"Failed to create table {table_name}: {e}")
        return table_name

    def insert_option_tick(self, option_symbol, tick_data):
        """
        Insert a tick (or OHLCV bar) into the option's table.
        tick_data: dict with keys: timestamp, open, high, low, close, volume, source
        """
        table_name = self.create_option_table(option_symbol)
        insert_sql = f"""
        INSERT INTO {table_name} (timestamp, open, high, low, close, volume, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        try:
            with self._write_lock:
                self.conn.execute(
                    insert_sql,
                    (
                        tick_data["timestamp"],
                        tick_data.get("open"),
                        tick_data.get("high"),
                        tick_data.get("low"),
                        tick_data.get("close"),
                        tick_data.get("volume"),
                        tick_data.get("source", "realtime"),
                    ),
                )
                self.conn.commit()
            logging.info(f"Inserted tick for {option_symbol} into {table_name}")
        except Exception as e:
            logging.error(f"Failed to insert tick for {option_symbol}: {e}")

    def save_results_to_db(self, df, table="strategy_results"):
        df = df.copy()
        # Convert all datetime columns and any pandas Timestamp objects in object columns to string for SQLite compatibility
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].astype(str)
            elif df[col].dtype == "object":
                # Convert any pandas Timestamp objects in object columns to string
                df[col] = df[col].apply(
                    lambda x: (
                        x.isoformat()
                        if hasattr(x, "isoformat")
                        else str(x) if isinstance(x, (pd.Timestamp,)) else x
                    )
                )
        with self._write_lock:
            with self.conn:
                try:
                    self.conn.execute(f"DROP TABLE IF EXISTS {table}")
                except Exception as e:
                    logger.warning(f"Failed to drop table {table}: {e}")
                
                # Use 'replace' (now that we dropped it, it will create new)
                # or 'fail' would also work since it doesn't exist.
                # 'replace' is safer in case the drop silently failed but table is empty/etc.
                df.to_sql(table, self.conn, if_exists="replace", index=False)

    def insert_option_historical(self, df: pd.DataFrame):
        with self._write_lock:
            with self.conn:
                df.to_sql(
                    "option_historical", self.conn, if_exists="append", index=False
                )

    def insert_strategy_results_bulk(self, df: pd.DataFrame):
        with self._write_lock:
            with self.conn:
                df.to_sql(
                    "strategy_results", self.conn, if_exists="append", index=False
                )

    def update_strategy_results(self, symbol, indicators, exit_signal, timestamp=None):
        timestamp = pd.to_datetime(timestamp or datetime.now())
        data = {
            "datetime": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            **indicators,
            "exit_signal": int(exit_signal),
        }
        df = pd.DataFrame([data])
        with self.conn:
            df.to_sql("strategy_results", self.conn, if_exists="append", index=False)

    def update_option_monitor_results(
        self,
        symbol: str,
        indicators: Optional[Dict] = None,
        trade_direction: Optional[str] = None,
        entry_price: Optional[float] = None,
        is_exit: bool = False,
        exit_reason: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ):
        """
        Insert a row into option_monitor_results.
        Ensures required columns exist and writes indicators into separate columns.
        """
        try:
            import sqlite3

            ts = timestamp or datetime.utcnow()
            ts_str = (
                ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
            )

            # Extract indicator values safely
            mcg5 = (
                float(indicators.get("MCG5"))
                if indicators and indicators.get("MCG5") is not None
                else None
            )
            mcg14 = (
                float(indicators.get("MCG14"))
                if indicators and indicators.get("MCG14") is not None
                else None
            )
            zlema7 = (
                float(indicators.get("ZLEMA7"))
                if indicators and indicators.get("ZLEMA7") is not None
                else None
            )
            zlema21 = (
                float(indicators.get("ZLEMA21"))
                if indicators and indicators.get("ZLEMA21") is not None
                else None
            )
            close_val = (
                float(indicators.get("close"))
                if indicators and indicators.get("close") is not None
                else None
            )

            # Required columns we may want to write
            desired_columns = {
                "timestamp": "TEXT",
                "symbol": "TEXT",
                "trade_direction": "TEXT",
                "entry_price": "REAL",
                "is_exit": "INTEGER",
                "exit_reason": "TEXT",
                "MCG5": "REAL",
                "MCG14": "REAL",
                "ZLEMA7": "REAL",
                "ZLEMA21": "REAL",
                "close": "REAL",
            }

            # Fetch existing columns for option_monitor_results
            try:
                rows = self.conn.execute(
                    "PRAGMA table_info(option_monitor_results)"
                ).fetchall()
                existing_cols = {r[1] for r in rows}
            except Exception:
                existing_cols = set()

            # Add any missing columns (best-effort)
            for col, col_type in desired_columns.items():
                if col not in existing_cols:
                    try:
                        self.conn.execute(
                            f"ALTER TABLE option_monitor_results ADD COLUMN {col} {col_type}"
                        )
                        logger.info(f"Added column {col} to option_monitor_results")
                        existing_cols.add(col)
                    except sqlite3.OperationalError as e:
                        # If ALTER fails (rare), continue — insertion will use available columns
                        logger.debug(f"Could not add column {col}: {e}")

            # Build columns and params for INSERT from available columns
            insert_order = []
            params = []

            mapping = {
                "timestamp": ts_str,
                "symbol": symbol,
                "trade_direction": trade_direction,
                "entry_price": float(entry_price) if entry_price is not None else None,
                "is_exit": int(bool(is_exit)),
                "exit_reason": exit_reason,
                "MCG5": mcg5,
                "MCG14": mcg14,
                "ZLEMA7": zlema7,
                "ZLEMA21": zlema21,
                "close": close_val,
            }

            for col in [
                "timestamp",
                "symbol",
                "trade_direction",
                "entry_price",
                "is_exit",
                "exit_reason",
                "MCG5",
                "MCG14",
                "ZLEMA7",
                "ZLEMA21",
                "close",
            ]:
                if col in existing_cols:
                    insert_order.append(col)
                    params.append(mapping[col])

            if not insert_order:
                raise RuntimeError(
                    "No writable columns found in option_monitor_results"
                )

            placeholders = ",".join(["?"] * len(insert_order))
            cols_sql = ",".join(insert_order)
            sql = f"INSERT INTO option_monitor_results ({cols_sql}) VALUES ({placeholders})"

            with self.conn:
                self.conn.execute(sql, tuple(params))

        except Exception as e:
            logger.error(f"Error updating option monitor results: {e}")
            raise

    def get_option_historical(self, symbol: str, limit: int = 1000) -> pd.DataFrame:
        """
        Get historical data for a specific option symbol.

        Args:
            symbol (str): The option symbol to fetch data for
            limit (int, optional): Maximum number of rows to return. Defaults to 1000.

        Returns:
            pd.DataFrame: DataFrame containing historical option data
        """
        try:
            query = """
            SELECT datetime, symbol, Open, High, Low, Close
            FROM option_historical 
            WHERE symbol = ?
            ORDER BY datetime DESC
            LIMIT ?
            """

            df = pd.read_sql_query(
                query, self.conn, params=(symbol, limit), parse_dates=["datetime"]
            )

            # Rename columns to match expected format
            df = df.rename(
                columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"}
            )

            return df

        except Exception as e:
            logger.error(f"Error fetching option historical data for {symbol}: {e}")
            return pd.DataFrame()  # Return empty DataFrame on error

    def update_option_historical(
        self,
        symbol: str,
        datetime: str,
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
        volume: int = 0,
        MCG5: float = 0,
        MCG14: float = 0,
        ZLEMA7: float = 0,
        ZLEMA21: float = 0,
    ):
        """Update option historical data with proper type conversion."""
        try:
            sql = """INSERT OR REPLACE INTO option_historical 
                    (datetime, symbol, Open, High, Low, Close, Volume, MCG5, MCG14, ZLEMA7, ZLEMA21)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

            params = (
                datetime,
                symbol,
                float(open_price),
                float(high_price),
                float(low_price),
                float(close_price),
                int(volume),
                float(MCG5),
                float(MCG14),
                float(ZLEMA7),
                float(ZLEMA21),
            )

            with self._write_lock:
                with self.conn:
                    self.conn.execute(sql, params)

        except Exception as e:
            logger.error(f"Error updating option historical: {str(e)}")
            raise


# Global instance
db = TradingDB()

