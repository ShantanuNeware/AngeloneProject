import json
import math
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Add parent directory to path so 'tradingsystem' can be imported when this file
# is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tradingsystem.config.loader import load_config


TEXT_COLUMNS = {
    "Zone",
    "Zone_5m",
    "Zone_15m",
    "Zone_60m",
    "Zone_240m",
    "ICT_Structure_Event",
    "ICT_Liquidity_Events",
    "ICT_Trend",
    "TREND",
    "ADX_SIGNAL",
    "Trade_Action",
    "Exit_Reason",
    "Strategy_State",
}


DEFAULT_INDICATOR_COLUMNS = [
    "ADX",
    "ATR",
    "ATR_Percent",
    "BB_Upper",
    "BB_Mid",
    "BB_Lower",
    "BB_Width",
    "EMA_9",
    "EMA_21",
    "EMA_50",
    "EMA_200",
    "EMA_Slope",
    "RSI",
    "RSI_Regular_Bullish",
    "RSI_Hidden_Bullish",
    "RSI_Regular_Bearish",
    "RSI_Hidden_Bearish",
    "SMI_5m",
    "SMI_15m",
    "SMI_60m",
    "SMI_240m",
    "SMI_Bullish_5m",
    "SMI_Bearish_5m",
    "LIQ_PRESSURE",
    "VOL_EXPANSION",
    "bull_div_3",
    "bear_div_3",
    "bull_div_15m",
    "bear_div_15m",
    "bear_div_60m",
    "ma_fast",
    "ma_slow",
    "adx",
    "atr",
    "rsi",
    "bb_upper",
    "bb_mid",
    "bb_lower",
    "strike",
    "premium",
    "stop_loss",
    "target_price",
]


class MarketDB:
    """
    SQLite persistence layer for live trading, analysis snapshots, backtests,
    reference levels, liquidity data, and active trade state.

    The class remains synchronous because the current trading engine is
    synchronous, but the schema mirrors the richer persistence service.
    """

    def __init__(self, db_path: Optional[str] = None, config: Optional[dict] = None):
        if db_path is None:
            db_path = Path(__file__).resolve().parents[2] / "database" / "trading_v4.db"
        else:
            db_path = Path(db_path)

        db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path
        self.config = config or self._load_config_safely()
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.row_factory = sqlite3.Row
        self.create_table()

    def _load_config_safely(self) -> dict:
        try:
            return load_config()
        except Exception:
            return {}

    def _sanitize_param(self, value: Any) -> Any:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if hasattr(value, "item"):
            return value.item()
        if isinstance(value, (list, dict)):
            return json.dumps(value)
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value

    def _normalize_symbol(self, symbol: Any) -> Optional[str]:
        if symbol is None:
            return None

        symbol_str = str(symbol).strip()
        if not symbol_str:
            return None
        if "|" in symbol_str:
            return symbol_str

        exchange = (
            self.config.get("strategy", {}).get("exchange")
            or self.config.get("brokers", {}).get("angleone", {}).get("exchange")
            or "NSE"
        )
        return f"{exchange}|{symbol_str}"

    def _indicator_snapshot_columns(self) -> List[str]:
        seen = set()
        columns = []
        for col in DEFAULT_INDICATOR_COLUMNS:
            sqlite_key = col.lower()
            if sqlite_key not in seen:
                columns.append(col)
                seen.add(sqlite_key)
        return columns

    def execute_query(self, query: str, params: Sequence[Any] = ()) -> None:
        sanitized = tuple(self._sanitize_param(param) for param in params)
        try:
            self.conn.execute(query, sanitized)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def execute_many_queries(self, query: str, params: Iterable[Sequence[Any]]) -> None:
        sanitized_batch = [
            tuple(self._sanitize_param(value) for value in row) for row in params
        ]
        try:
            self.conn.executemany(query, sanitized_batch)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def fetch_rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]

    def create_table(self) -> None:
        self._create_legacy_candles_table()
        self._create_core_tables()
        self._create_strategy_history_table()
        self._create_ict_tables()
        self._create_backtest_tables()
        self._create_active_trades_table()
        self._migrate_existing_tables()

    def _create_legacy_candles_table(self) -> None:
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS candles (
                timestamp TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                token TEXT,
                UNIQUE(timestamp, token)
            )
            """
        )

    def _create_core_tables(self) -> None:
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS signals (
                timestamp TEXT PRIMARY KEY,
                symbol TEXT,
                side TEXT,
                price REAL,
                reason TEXT
            )
            """
        )
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS realtime (
                timestamp TEXT,
                Symbol TEXT,
                Open REAL,
                High REAL,
                Low REAL,
                Close REAL,
                Volume INTEGER,
                PRIMARY KEY (timestamp, Symbol)
            )
            """
        )
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                Symbol TEXT NOT NULL,
                indicator_name TEXT NOT NULL,
                indicator_value REAL,
                UNIQUE(Symbol, timestamp, indicator_name)
            )
            """
        )
        self.execute_query(
            """
            CREATE INDEX IF NOT EXISTS idx_indicators_symbol_timestamp
            ON indicators(Symbol, timestamp)
            """
        )
        self.execute_query(
            """
            CREATE INDEX IF NOT EXISTS idx_indicators_name
            ON indicators(indicator_name)
            """
        )

    def _create_strategy_history_table(self) -> None:
        base_columns = [
            "timestamp TEXT PRIMARY KEY",
            "Symbol TEXT",
            "Open REAL",
            "High REAL",
            "Low REAL",
            "Close REAL",
            "Volume INTEGER",
        ]

        existing_column_names = {col.split()[0].lower() for col in base_columns}
        for col in self._indicator_snapshot_columns():
            if col.lower() in existing_column_names:
                continue
            dtype = "TEXT" if col in TEXT_COLUMNS else "REAL"
            base_columns.append(f"{col} {dtype}")
            existing_column_names.add(col.lower())

        for state_col in (
            "Trade_Action TEXT",
            "Exit_Reason TEXT",
            "Strategy_State TEXT",
            "Stop_Loss REAL",
        ):
            col_name = state_col.split()[0]
            if col_name.lower() not in existing_column_names:
                base_columns.append(state_col)
                existing_column_names.add(col_name.lower())

        self.execute_query(
            f"""
            CREATE TABLE IF NOT EXISTS strategy_history (
                {", ".join(base_columns)}
            )
            """
        )

    def _create_ict_tables(self) -> None:
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS reference_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timeframe TEXT,
                level_type TEXT,
                price REAL,
                session_date TEXT,
                created_at TEXT,
                data_source TEXT,
                UNIQUE(symbol, timeframe, level_type, session_date)
            )
            """
        )
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS liquidity_pools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timeframe TEXT,
                level_type TEXT,
                price REAL,
                side TEXT,
                external INTEGER,
                swept INTEGER,
                sweep_time TEXT,
                created_at TEXT,
                source_time INTEGER,
                data_source TEXT,
                UNIQUE(symbol, timeframe, level_type, price, source_time)
            )
            """
        )
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS structure_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timeframe TEXT,
                event_type TEXT,
                price REAL,
                timestamp TEXT,
                data_source TEXT
            )
            """
        )
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timeframe TEXT,
                zone_type TEXT,
                high REAL,
                low REAL,
                mitigated INTEGER,
                mitigated_time TEXT,
                created_at TEXT,
                data_source TEXT
            )
            """
        )

    def _create_backtest_tables(self) -> None:
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backtest_id TEXT,
                symbol TEXT,
                start_date TEXT,
                end_date TEXT,
                total_trades INTEGER,
                net_profit REAL,
                win_rate REAL,
                profit_factor REAL,
                max_drawdown_pct REAL,
                sharpe_ratio REAL,
                total_points REAL,
                starting_capital REAL,
                commission REAL,
                slippage_pct REAL,
                risk_per_trade REAL,
                created_at TEXT,
                UNIQUE(backtest_id, symbol, start_date, end_date)
            )
            """
        )
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backtest_id TEXT,
                trade_id INTEGER,
                symbol TEXT,
                direction TEXT,
                entry_time TEXT,
                entry_price REAL,
                exit_time TEXT,
                exit_price REAL,
                size REAL,
                points REAL,
                gross_profit REAL,
                commission REAL,
                net_profit REAL,
                exit_reason TEXT,
                stop_loss REAL,
                created_at TEXT,
                UNIQUE(backtest_id, trade_id)
            )
            """
        )

    def _create_active_trades_table(self) -> None:
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS active_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id TEXT UNIQUE,
                option_symbol TEXT,
                index_symbol TEXT,
                side TEXT,
                entry_price REAL,
                option_entry_price REAL,
                quantity INTEGER,
                tsl_price REAL,
                pt_price REAL,
                last_tsl REAL,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                closed_at TEXT,
                exit_reason TEXT,
                error_message TEXT
            )
            """
        )
        self.execute_query(
            """
            CREATE INDEX IF NOT EXISTS idx_active_trades_symbol
            ON active_trades(option_symbol)
            """
        )

    def _migrate_existing_tables(self) -> None:
        self._add_column_if_missing("candles", "token", "TEXT")
        self._add_column_if_missing("realtime", "Volume", "INTEGER")

        strategy_columns = {
            "Open": "REAL",
            "High": "REAL",
            "Low": "REAL",
            "Close": "REAL",
            "Volume": "INTEGER",
            "Trade_Action": "TEXT",
            "Exit_Reason": "TEXT",
            "Strategy_State": "TEXT",
            "Stop_Loss": "REAL",
            "ICT_Structure_Event": "TEXT",
            "ICT_Liquidity_Events": "TEXT",
            "ICT_Trend": "TEXT",
        }
        for col in self._indicator_snapshot_columns():
            strategy_columns[col] = "TEXT" if col in TEXT_COLUMNS else "REAL"
        for col, dtype in strategy_columns.items():
            self._add_column_if_missing("strategy_history", col, dtype)

        for table in ("reference_levels", "liquidity_pools", "structure_events", "zones"):
            self._add_column_if_missing(table, "data_source", "TEXT")

    def _add_column_if_missing(self, table: str, column: str, dtype: str) -> None:
        rows = self.fetch_rows(f"PRAGMA table_info({table})")
        existing_cols = {row["name"].lower() for row in rows}
        if column.lower() not in existing_cols:
            self.execute_query(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}")

    def insert_candles(self, candles: Sequence[Sequence[Any]], token: str) -> None:
        if not candles:
            print("No candles to insert")
            return

        data = []
        realtime_rows = []
        symbol = self._normalize_symbol(token)

        for candle in candles:
            if len(candle) < 6:
                continue

            timestamp = self._sanitize_param(candle[0])
            open_price = float(candle[1])
            high = float(candle[2])
            low = float(candle[3])
            close = float(candle[4])
            volume = float(candle[5])

            data.append((timestamp, open_price, high, low, close, volume, token))
            realtime_rows.append(
                (timestamp, symbol, open_price, high, low, close, int(volume))
            )

        if not data:
            print("No valid candles to insert")
            return

        self.execute_many_queries(
            """
            INSERT OR IGNORE INTO candles
            (timestamp, open, high, low, close, volume, token)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            data,
        )
        self.execute_many_queries(
            """
            INSERT OR REPLACE INTO realtime
            (timestamp, Symbol, Open, High, Low, Close, Volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            realtime_rows,
        )
        print(f"Inserted {len(data)} rows")

    def upsert_candle(
        self,
        token: str,
        timestamp: Any,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float = 0,
    ) -> None:
        """Insert or update one live candle in both candles and realtime tables."""
        timestamp = self._sanitize_param(timestamp)
        symbol = self._normalize_symbol(token)
        values = (
            timestamp,
            float(open_price),
            float(high),
            float(low),
            float(close),
            float(volume or 0),
            str(token),
        )
        self.execute_query(
            """
            INSERT INTO candles (timestamp, open, high, low, close, volume, token)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(timestamp, token) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume
            """,
            values,
        )
        self.execute_query(
            """
            INSERT OR REPLACE INTO realtime
            (timestamp, Symbol, Open, High, Low, Close, Volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                symbol,
                float(open_price),
                float(high),
                float(low),
                float(close),
                int(volume or 0),
            ),
        )

    def get_candle_models(
        self,
        token: Optional[str] = None,
        limit: int = 500,
        symbol: Optional[str] = None,
        timeframe: str = "1m",
    ) -> List["Candle"]:
        """Fetch recent candles as Candle models in chronological order."""
        from tradingsystem.models import Candle

        params: List[Any] = []
        where = ""
        if token:
            where = "WHERE token=?"
            params.append(str(token))

        params.append(int(limit))
        rows = self.fetch_rows(
            f"""
            SELECT timestamp, open, high, low, close, volume, token
            FROM candles
            {where}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            tuple(params),
        )

        candles: List[Candle] = []
        for row in reversed(rows):
            try:
                ts = row["timestamp"]
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                candle_symbol = symbol or row.get("token") or token or ""
                candles.append(
                    Candle(
                        symbol=str(candle_symbol),
                        timeframe=timeframe,
                        timestamp=ts,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(row.get("volume") or 0),
                    )
                )
            except Exception:
                continue

        return candles

    def save_ohlc(self, table: str, data: Dict[str, Any]) -> None:
        expected_cols = ["timestamp", "Symbol", "Open", "High", "Low", "Close", "Volume"]
        values = [data.get(col) for col in expected_cols]
        values[1] = self._normalize_symbol(values[1])
        cols = ", ".join(expected_cols)
        placeholders = ", ".join(["?"] * len(expected_cols))
        self.execute_query(
            f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})",
            values,
        )

    def create_option_table(self, table_name: str) -> None:
        """Create a per-option table to store ticks and greeks for a specific option symbol."""
        self.execute_query(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                timestamp TEXT,
                token TEXT,
                strike REAL,
                option_type TEXT,
                bid REAL,
                ask REAL,
                ltp REAL,
                volume INTEGER,
                oi INTEGER,
                iv REAL,
                delta REAL,
                gamma REAL,
                theta REAL,
                vega REAL,
                PRIMARY KEY(timestamp, token)
            )
            """
        )

    def insert_option_tick(self, table_name: str, row: Dict[str, Any]) -> None:
        """Insert or replace a single option tick row into the named option table.

        Expected keys: timestamp, token, strike, option_type, bid, ask, ltp, volume, oi, iv, delta, gamma, theta, vega
        """
        cols = [
            "timestamp",
            "token",
            "strike",
            "option_type",
            "bid",
            "ask",
            "ltp",
            "volume",
            "oi",
            "iv",
            "delta",
            "gamma",
            "theta",
            "vega",
        ]
        values = [self._sanitize_param(row.get(c)) for c in cols]
        placeholders = ", ".join(["?"] * len(cols))
        cols_sql = ", ".join(cols)
        self.execute_query(
            f"INSERT OR REPLACE INTO {table_name} ({cols_sql}) VALUES ({placeholders})",
            values,
        )

    def insert_signal(self, symbol: str, side: str, price: float, reason: str) -> None:
        now = datetime.now().isoformat()
        self.execute_query(
            """
            INSERT OR REPLACE INTO signals (timestamp, symbol, side, price, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now, self._normalize_symbol(symbol), side, price, reason),
        )

    def save_signal(self, signal: Any) -> None:
        self.insert_signal(
            symbol=getattr(signal, "symbol", ""),
            side=getattr(getattr(signal, "signal_type", ""), "value", ""),
            price=float(getattr(signal, "price", 0.0)),
            reason=getattr(signal, "reason", "") or "",
        )

    def save_strategy_state(self, state: Dict[str, Any]) -> None:
        table_columns = {row["name"] for row in self.fetch_rows("PRAGMA table_info(strategy_history)")}
        cols_to_save = []
        values = []

        for col_name in sorted(table_columns):
            value = None
            state_key_map = {str(key).lower(): key for key in state.keys()}

            if col_name == "timestamp":
                value = state.get("timestamp") or state.get("Timestamp")
            elif col_name == "Symbol":
                value = self._normalize_symbol(state.get("Symbol") or state.get("symbol"))
            elif col_name in state:
                value = state[col_name]
            elif col_name.lower() in state_key_map:
                value = state[state_key_map[col_name.lower()]]

            value = self._sanitize_param(value)
            if value is not None:
                cols_to_save.append(col_name)
                values.append(value)

        if not cols_to_save:
            return

        cols = ", ".join(cols_to_save)
        placeholders = ", ".join(["?"] * len(cols_to_save))
        self.execute_query(
            f"INSERT OR REPLACE INTO strategy_history ({cols}) VALUES ({placeholders})",
            values,
        )
        self.save_indicator_snapshot(state)

    def save_strategy_states_batch(self, states: Sequence[Dict[str, Any]]) -> None:
        if not states:
            return

        table_columns = {row["name"] for row in self.fetch_rows("PRAGMA table_info(strategy_history)")}
        cols_with_values = set()
        for state in states:
            state_key_map = {str(key).lower(): key for key in state.keys()}
            for col_name in table_columns:
                if col_name == "timestamp" and (state.get("timestamp") or state.get("Timestamp")):
                    cols_with_values.add(col_name)
                elif col_name == "Symbol" and (state.get("Symbol") or state.get("symbol")):
                    cols_with_values.add(col_name)
                elif col_name in state and self._sanitize_param(state[col_name]) is not None:
                    cols_with_values.add(col_name)
                elif (
                    col_name.lower() in state_key_map
                    and self._sanitize_param(state[state_key_map[col_name.lower()]]) is not None
                ):
                    cols_with_values.add(col_name)

        if not cols_with_values:
            return

        cols_to_save = sorted(cols_with_values)
        all_values = []
        for state in states:
            state_key_map = {str(key).lower(): key for key in state.keys()}
            values = []
            for col_name in cols_to_save:
                if col_name == "timestamp":
                    value = state.get("timestamp") or state.get("Timestamp")
                elif col_name == "Symbol":
                    value = self._normalize_symbol(state.get("Symbol") or state.get("symbol"))
                elif col_name in state:
                    value = state.get(col_name)
                elif col_name.lower() in state_key_map:
                    value = state.get(state_key_map[col_name.lower()])
                else:
                    value = None
                values.append(self._sanitize_param(value))
            all_values.append(tuple(values))

        cols = ", ".join(cols_to_save)
        placeholders = ", ".join(["?"] * len(cols_to_save))
        self.execute_many_queries(
            f"INSERT OR REPLACE INTO strategy_history ({cols}) VALUES ({placeholders})",
            all_values,
        )
        self._save_indicator_snapshots_batch(states)

    def save_indicator_snapshot(self, state: Dict[str, Any]) -> None:
        rows = self._build_indicator_rows([state])
        if rows:
            self._insert_indicator_rows(rows)

    def _save_indicator_snapshots_batch(self, states: Sequence[Dict[str, Any]]) -> None:
        rows = self._build_indicator_rows(states)
        if rows:
            self._insert_indicator_rows(rows)

    def _build_indicator_rows(
        self, states: Sequence[Dict[str, Any]]
    ) -> List[Tuple[Any, str, str, float]]:
        indicator_cols = self._indicator_snapshot_columns()
        rows = []

        for state in states:
            timestamp = state.get("timestamp") or state.get("Timestamp")
            symbol = state.get("Symbol") or state.get("symbol")
            if not timestamp or not symbol:
                continue

            state_key_map = {str(key).lower(): key for key in state.keys()}
            normalized_symbol = self._normalize_symbol(symbol)
            for name in indicator_cols:
                key = name if name in state else state_key_map.get(name.lower())
                value = self._sanitize_param(state.get(key))
                if isinstance(value, bool):
                    value = int(value)
                if isinstance(value, (int, float)):
                    rows.append((timestamp, normalized_symbol, name, float(value)))

        return rows

    def _insert_indicator_rows(self, rows: Sequence[Tuple[Any, str, str, float]]) -> None:
        self.execute_many_queries(
            """
            INSERT OR REPLACE INTO indicators
            (timestamp, Symbol, indicator_name, indicator_value)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )

    def save_backtest_results(
        self,
        backtest_id: str,
        symbol: str,
        start_date: str,
        end_date: str,
        metrics: Dict[str, Any],
        config_params: Dict[str, Any],
    ) -> None:
        def extract_numeric(value: Any) -> float:
            if isinstance(value, str):
                value = value.replace(",", "").replace("%", "")
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        self.execute_query(
            """
            INSERT OR REPLACE INTO backtest_results
            (backtest_id, symbol, start_date, end_date, total_trades, net_profit,
             win_rate, profit_factor, max_drawdown_pct, sharpe_ratio, total_points,
             starting_capital, commission, slippage_pct, risk_per_trade, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                backtest_id,
                self._normalize_symbol(symbol),
                start_date,
                end_date,
                metrics.get("Total Trades", 0),
                extract_numeric(metrics.get("Net Profit", 0)),
                extract_numeric(metrics.get("Win Rate", 0)),
                extract_numeric(metrics.get("Profit Factor", 0)),
                extract_numeric(metrics.get("Max Drawdown %", 0)),
                extract_numeric(metrics.get("Sharpe Ratio", 0)),
                extract_numeric(metrics.get("Total Points", 0)),
                config_params.get("starting_capital", 0),
                config_params.get("commission", 0),
                config_params.get("slippage_pct", 0),
                config_params.get("risk_per_trade", 0),
            ),
        )

    def save_backtest_trades(self, backtest_id: str, trades: Sequence[Dict[str, Any]]) -> None:
        rows = []
        for trade_idx, trade in enumerate(trades):
            rows.append(
                (
                    backtest_id,
                    trade_idx + 1,
                    self._normalize_symbol(trade.get("symbol", "")),
                    trade.get("direction", ""),
                    trade.get("entry_time", ""),
                    trade.get("entry_price", 0),
                    trade.get("exit_time", ""),
                    trade.get("exit_price", 0),
                    trade.get("size", 0),
                    trade.get("points", 0),
                    trade.get("gross_profit", 0),
                    trade.get("commission", 0),
                    trade.get("profit", 0),
                    trade.get("exit_reason", ""),
                    trade.get("stop_loss", 0),
                )
            )

        if rows:
            self.execute_many_queries(
                """
                INSERT OR REPLACE INTO backtest_trades
                (backtest_id, trade_id, symbol, direction, entry_time, entry_price,
                 exit_time, exit_price, size, points, gross_profit, commission,
                 net_profit, exit_reason, stop_loss, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                rows,
            )

    def cleanup_old_data(self, retention_days: int) -> None:
        cutoff_str = (datetime.now() - timedelta(days=retention_days)).isoformat()
        for table in ("realtime", "signals", "strategy_history", "indicators"):
            timestamp_col = "timestamp"
            try:
                self.execute_query(f"DELETE FROM {table} WHERE {timestamp_col} < ?", (cutoff_str,))
            except sqlite3.Error:
                continue

    def get_candles(self, token: str, limit: int = 100) -> List[Tuple[Any, ...]]:
        cursor = self.conn.execute(
            """
            SELECT timestamp, open, high, low, close, volume, token
            FROM candles
            WHERE token=?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (token, limit),
        )
        return cursor.fetchall()

    def fetch_ohlc_data(self, table: str = "realtime", limit: int = 1500) -> List[Dict[str, Any]]:
        return self.fetch_rows(
            f"SELECT * FROM {table} ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )

    def delete_candles(self) -> None:
        self.execute_query("DELETE FROM candles")
        self.execute_query("DELETE FROM realtime")

    def close(self) -> None:
        if self.conn:
            self.conn.close()
