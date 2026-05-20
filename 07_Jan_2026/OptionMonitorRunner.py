import datetime
import time
from typing import Dict
import sqlite3
import pandas as pd
import logging
from collections import deque

from database.db_writer import enqueue as db_enqueue
from utils import (
    get_positions,
    get_available_balance,
    place_order,
    searchscript,
    get_ltp,
)
from Shoonya.LoginHelper import login, api
import threading
from OptionMonitor import Strategy_Indicators, generate_trade_signals
from database import db
from database.db_writer import (
    start as start_db_writer,
    stop as stop_db_writer,
)
from database.database import (
    db as db_obj,
)
from config import OptionChain_data_interval
import config

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(threadName)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Timezone for India (IST)
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

# Constants
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


active_monitors: Dict[str, "OptionMonitorRunner"] = {}


# Global exit signal from StrategyData
_strategy_exit_signal = {
    "CALL_EXIT": False,
    "PUT_EXIT": False
}
_signal_lock = threading.Lock()

def signal_exit_to_monitors(action):
    """Called by StrategyData to signal exit to all monitors."""
    with _signal_lock:
        if action == "CALL_EXIT":
            _strategy_exit_signal["CALL_EXIT"] = True
            logger.info("🔔 EXIT signal sent to CALL monitors")
        elif action == "PUT_EXIT":
            _strategy_exit_signal["PUT_EXIT"] = True
            logger.info("🔔 EXIT signal sent to PUT monitors")

def check_strategy_exit_signal(signal_type):
    """Check if StrategyData has signaled exit."""
    with _signal_lock:
        if signal_type == "CALL":
            return _strategy_exit_signal["CALL_EXIT"]
        elif signal_type == "PUT":
            return _strategy_exit_signal["PUT_EXIT"]
    return False

def clear_exit_signal(signal_type):
    """Clear exit signal after processing."""
    with _signal_lock:
        if signal_type == "CALL":
            _strategy_exit_signal["CALL_EXIT"] = False
        elif signal_type == "PUT":
            _strategy_exit_signal["PUT_EXIT"] = False


def start_option_monitor(signal_type: str):
    """Start a monitor for given signal type (CALL or PUT)."""
    # Use signal_type as key since we don't have specific option yet
    monitor_key = f"{signal_type}_monitor"
    
    if monitor_key in active_monitors:
        logger.info(f"Monitor for {signal_type} already active.")
        return
    
    logger.info(f"Starting OptionMonitor for {signal_type}...")
    try:
        stop_event = threading.Event()
        # USE REALTIME RUNNER
        from OptionMonitorRunner_RT import OptionMonitorRunner_RT
        monitor = OptionMonitorRunner_RT(
            stop_event=stop_event,
            signal_type=signal_type,  # Pass signal type, not specific option
        )
        monitor.start()
        active_monitors[monitor_key] = monitor
        
        # Ensure background updater is running
        start_monitor_updater()
    except Exception as e:
        logger.exception(f"Failed to start OptionMonitor for {signal_type}: {e}")


def stop_option_monitor(signal_type: str):
    monitor_key = f"{signal_type}_monitor"
    monitor = active_monitors.get(monitor_key)
    if monitor:
        logger.info(f"Stopping OptionMonitor for {signal_type}...")
        try:
            monitor.stop()
        except Exception as e:
            logger.exception(f"Error stopping OptionMonitor for {signal_type}: {e}")
        finally:
            if monitor_key in active_monitors:
                del active_monitors[monitor_key]
    else:
        logger.warning(f"No active monitor found for {signal_type} to stop.")


def update_active_monitors():
    """Iterate through all active monitors and update their real-time data."""
    if not active_monitors:
        return
    symbols = list(active_monitors.keys())
    for symbol in symbols:
        monitor = active_monitors.get(symbol)
        if monitor:
            try:
                # Only update if monitor has selected a symbol
                if monitor.symbol:
                    monitor.update_realtime_candles(monitor.symbol, interval=OptionChain_data_interval)
            except Exception as e:
                logger.error(f"Failed to update monitor for {symbol}: {e}")


# --- Background Updater Thread ---
_updater_thread = None
_updater_running = False

def _monitor_updater_loop():
    """Background loop to update monitors every 1 second (LTP-based)."""
    global _updater_running
    logger.info("🔄 Monitor Updater Thread STARTED")
    while _updater_running:
        try:
            update_active_monitors()
        except Exception as e:
            logger.error(f"Error in monitor updater loop: {e}")
        
        # Sleep for 1 second (LTP-based updates are fast)
        time.sleep(1)
    logger.info("⏹️ Monitor Updater Thread STOPPED")

def start_monitor_updater():
    """Start the background updater thread if not running."""
    global _updater_thread, _updater_running
    if not _updater_running:
        _updater_running = True
        _updater_thread = threading.Thread(target=_monitor_updater_loop, daemon=True)
        _updater_thread.start()


class OptionMonitorRunner:
    """
    OptionMonitorRunner:
    - Keeps merged dataframes of bars
    - Receives option chain snapshots via self.latest_option_chain
    - Generates signals via Strategy_Indicators
    - Executes trades via place_order (real or trial)
    """

    def __init__(
        self,
        stop_event: threading.Event,
        signal_type: str,  # "CALL" or "PUT" - not specific option
        trial_mode: bool = True,
        max_bars: int = 1500,
    ):
        # Execution / threading
        self.stop_event = stop_event
        self.signal_type = signal_type  # Store signal type
        self.tradingsymbol = None  # Will be set after option selection
        self.symbol = None  # Will be set after option selection
        self.db = db_obj

        self.trial_mode = trial_mode
        self.logger = logging.getLogger(f"OptionMonitor[{signal_type}]")
        self.logger.setLevel(logging.DEBUG)
        self.lot_size = 75

        self.signal_queue = deque()
        self.data_lock = threading.Lock()
        self.merged_df = pd.DataFrame()
        self.rt_buffer = deque()
        self.max_bars = max_bars

        # Track position state
        self.in_position = False

        # Boundary candle tracking (for LTP-based candle building)
        self.last_candle_boundary_minute = None
        self._first_candle_initialized = False
        self.current_candle = None
        self.current_interval = OptionChain_data_interval  # Default interval for options

        # NOTE: Don't load historical data yet - we need to select option first!

        # Track active monitors (if needed)
        self.active_monitors = {}

        start_db_writer()

    def select_and_initialize_option(self):
        """
        Fetch option chain, select best option, validate PCR/gamma.
        Sets self.tradingsymbol and self.symbol.
        Returns True if successful, False otherwise.
        """
        from optionchainfetcher import get_pcr_and_option_data, select_best_option
        
        try:
            # 1. Fetch option chain with PCR
            self.logger.info(f"🔍 Fetching option chain for {self.signal_type}...")
            merged_df, pcr, prediction = get_pcr_and_option_data(force_refresh=True)
            
            if merged_df is None or merged_df.empty:
                self.logger.error("❌ Option chain not available - API may be down or no data returned")
                return False
            
            self.logger.info(
                f"📊 Option chain fetched: {len(merged_df)} strikes, "
                f"PCR={pcr:.2f}, Prediction={prediction}"
            )
            
            # ---------------------------------------------------------
            # 2. Validate PCR with buffer zone (safer than strict 1.0)
            # CALL allowed only when PCR < 0.98
            # PUT allowed only when PCR > 1.02
            # ---------------------------------------------------------
            
            CALL_THRESHOLD = config.PCR_THRESHOLD_CALL
            PUT_THRESHOLD  = config.PCR_THRESHOLD_PUT

            if self.signal_type == "CALL" and pcr >= CALL_THRESHOLD:
                self.logger.warning(
                    f"❌ PCR too high for CALL ({pcr:.2f} >= {CALL_THRESHOLD}), market not bullish - skipping"
                )
                return False
            
            elif self.signal_type == "PUT" and pcr <= PUT_THRESHOLD:
                self.logger.warning(
                    f"❌ PCR too low for PUT ({pcr:.2f} <= {PUT_THRESHOLD}), market not bearish - skipping"
                )
                return False
            
            self.logger.info(f"✅ PCR validation passed for {self.signal_type} (PCR={pcr:.2f})")
            
            # 3. Select best option
            available_balance = get_available_balance()
            self.logger.info(f"💰 Available balance: ₹{available_balance:.2f}")
            
            ltp_col = "ltp_CE" if self.signal_type == "CALL" else "ltp_PE"
            best_option = select_best_option(
                merged_df, self.signal_type, available_balance, ltp_col=ltp_col
            )
            
            if not best_option:
                self.logger.error(
                    f"❌ No suitable {self.signal_type} option found - all options may be too expensive or no strikes available"
                )
                return False
            
            # 4. Set option details
            self.tradingsymbol = best_option["tradingsymbol"]
            token = searchscript("NFO", self.tradingsymbol)
            self.symbol = str(token)
            
            self.logger.info(
                f"✅ Selected {self.signal_type} option: {self.tradingsymbol} "
                f"(PCR={pcr:.2f}, strike={best_option['strike']}, "
                f"cost=₹{best_option.get('cost_per_lot', 0):.2f})"
            )
            
            return True
        
        except Exception as e:
            self.logger.exception(f"❌ Error selecting option: {e}")
            return False


    def start(self):
        """Start the monitor in a separate thread."""
        # Clear database tables on start
        try:
            self._clear_table("option_historical")
            self._clear_table("option_strategy_results")
            self.logger.warning("🗑️ CLEARED ALL database tables on START")
        except Exception as e:
            self.logger.exception(f"Error clearing database tables: {e}")

        # Historical check for unresolved CALL
        self.logger.info(
            f"Checking historical signals for unresolved CALL on {self.symbol}..."
        )
        self.check_and_process_historical_signals()

        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the monitor."""
        self.logger.info(f"Stopping monitor for {self.symbol}...")
        self.stop_event.set()
        if hasattr(self, "thread") and self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
            if self.thread.is_alive():
                self.logger.warning(
                    f"Monitor thread for {self.symbol} did not stop within timeout!"
                )
            else:
                self.logger.info(
                    f"Monitor thread for {self.symbol} stopped successfully."
                )

        # Clear database tables on stop
        try:
            self._clear_table("option_historical")
            self._clear_table("option_strategy_results")
            self.logger.warning("🗑️ CLEARED ALL database tables on STOP")
        except Exception as e:
            self.logger.exception(f"Error clearing database tables: {e}")

    def _clear_table(self, table_name: str):
        """Clear ALL rows from the specified table (not symbol-specific)."""
        try:
            with self.db.conn:
                self.db.conn.execute(f"DELETE FROM {table_name}")
                self.logger.debug(f"Cleared all rows from {table_name}")
        except Exception:
            self.logger.exception(f"Failed to clear {table_name}")

    def _init_live_candle(self, symbol: str, ltp: float, interval: int):
        """Initialize a fresh live candle aligned to the current interval boundary.
        
        The candle timestamp is forced to the correct boundary minute (minute floored to interval).
        """
        # Force numeric
        ltp = float(ltp)
        now = datetime.datetime.now(tz=IST)
        # Align minute to interval boundary
        boundary_minute = (now.minute // interval) * interval
        now_boundary = now.replace(minute=boundary_minute, second=0, microsecond=0)

        self.current_candle = {
            "Symbol": symbol,
            "DateTime": now_boundary,  # store as datetime (tz-aware)
            "Date": now_boundary.date(),
            "Time": now_boundary.time().strftime("%H:%M:%S"),
            "Open": ltp,
            "High": ltp,
            "Low": ltp,
            "Close": ltp,
        }
        self.current_interval = interval
        self.current_candle_minute = now_boundary.minute

        # Mark boundary and first init
        self.last_candle_boundary_minute = now_boundary.minute
        self._first_candle_initialized = True

    def update_live_candle_from_ltp(self, symbol: str, interval: int = 1):
        """Build and finalize live candles using LTP snapshots.
        
        - A new candle is created ONLY when clock hits an interval boundary
          e.g., for interval=1: minutes 0,1,2,3,...
        - Completed candle is appended to rt_buffer as a dict with DateTime as tz-aware datetime
        """
        try:
            # Get LTP
            ltp = get_ltp(symbol)
            if not ltp or ltp <= 0:
                return
            
            ltp = float(ltp)
            now = datetime.datetime.now(tz=IST)
            minute = now.minute

            # --- FIRST EVER CANDLE ---
            if not getattr(self, "current_candle", None) or not self._first_candle_initialized:
                self._init_live_candle(symbol, ltp, interval)
                return

            # Normalize current time to boundary minute for consistent timestamps
            boundary_minute = (now.minute // interval) * interval
            now_boundary = now.replace(minute=boundary_minute, second=0, microsecond=0)

            # NEW CANDLE CONDITION:
            #  1) minute at boundary (minute % interval == 0)
            #  2) not same boundary we've already handled
            if (minute % interval == 0) and (self.last_candle_boundary_minute != now_boundary.minute):
                # close previous candle
                with self.data_lock:
                    # ensure DateTime is datetime and consistent type
                    finished = self.current_candle.copy()
                    # already a datetime in current_candle["DateTime"]
                    self.rt_buffer.append(finished)

                # start new candle
                self._init_live_candle(symbol, ltp, interval)

                # mark handled boundary
                self.last_candle_boundary_minute = now_boundary.minute
                return

            # Otherwise update current candle in-memory
            # Ensure numeric comparisons
            self.current_candle["High"] = max(float(self.current_candle["High"]), ltp)
            self.current_candle["Low"] = min(float(self.current_candle["Low"]), ltp)
            self.current_candle["Close"] = float(ltp)

        except Exception as e:
            self.logger.exception(f"Error updating live candle: {e}")

    def _bulk_insert_historical(self, rows):
        """
        Bulk insert for historical OHLC + indicators into option_historical table.
        Uses a direct sqlite3 connection to improve speed.
        """
        if not rows:
            return
        try:
            conn = sqlite3.connect(
                getattr(self.db, "_db_path", r"E:\WORKSPACE\SHOONYA PROJECTS\28_Nov_2025\database\trading.db"),
                timeout=10,
            )
            cursor = conn.cursor()
            insert_query = """
            INSERT OR REPLACE INTO option_historical
            (symbol, datetime, Open, High, Low, Close, Volume, MCG5, MCG14, ZLEMA7, ZLEMA21)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            data = []
            for row in rows:
                dt = row.get("DateTime")
                if isinstance(dt, (pd.Timestamp, datetime.datetime)):
                    dt = pd.to_datetime(dt).strftime(DATETIME_FORMAT)
                dt = str(dt)
                data.append(
                    (
                        row.get("Symbol", self.symbol),
                        dt,
                        safe_float(row.get("Open", 0.0)),
                        safe_float(row.get("High", 0.0)),
                        safe_float(row.get("Low", 0.0)),
                        safe_float(row.get("Close", 0.0)),
                        int(row.get("Volume", 0)) if row.get("Volume") is not None else 0,
                        safe_float(row.get("MCG5", 0.0)),
                        safe_float(row.get("MCG14", 0.0)),
                        safe_float(row.get("ZLEMA7", 0.0)),
                        safe_float(row.get("ZLEMA21", 0.0)),
                    )
                )
            cursor.executemany(insert_query, data)
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.exception("Bulk insert failed: %s", e)

    def merge_buffers(self) -> None:
        """Merge buffered real-time bars into merged_df, avoiding duplicates."""
        with self.data_lock:
            if not self.rt_buffer:
                return
            new_bars_df = pd.DataFrame(list(self.rt_buffer))
            self.rt_buffer.clear()
            if new_bars_df.empty:
                return
            
            # Ensure DateTime column is datetime dtype (preserves tz)
            if "DateTime" in new_bars_df.columns:
                new_bars_df["DateTime"] = pd.to_datetime(new_bars_df["DateTime"])
            
            if self.merged_df.empty:
                self.merged_df = new_bars_df.copy()
                logger.info("Initialized merged_df with first real-time batch.")
            else:
                existing_times = set(self.merged_df["DateTime"].astype(str))
                new_bars_df = new_bars_df[
                    ~new_bars_df["DateTime"].astype(str).isin(existing_times)
                ]
                if new_bars_df.empty:
                    logger.debug("No new unique candles to append to merged_df.")
                    return
                self.merged_df = pd.concat(
                    [self.merged_df, new_bars_df], ignore_index=True
                )
                self.merged_df = (
                    self.merged_df.sort_values(by="DateTime", ascending=True)
                    .reset_index(drop=True)
                )
                if len(self.merged_df) > self.max_bars:
                    self.merged_df = (
                        self.merged_df.iloc[-self.max_bars :]
                        .reset_index(drop=True)
                    )
                logger.info(
                    f"Merged new {len(new_bars_df)} bars → total: {len(self.merged_df)} rows."
                )

    def get_time(self, time_string: str) -> float:
        return time.mktime(time.strptime(time_string, "%d-%m-%Y %H:%M:%S"))

    def realtimeCandles(self, symbol, days, interval, exchange="NFO"):
        """Load historical candles from Shoonya and return a DataFrame with datetime DateTime column (tz-aware).
        
        This is used to backfill merged_df on startup.
        """
        now_dt = datetime.datetime.now(tz=IST)
        start_dt = now_dt - datetime.timedelta(days=days)
        now = now_dt.strftime("%d-%m-%Y %H:%M:%S")
        start_time = start_dt.strftime("%d-%m-%Y %H:%M:%S")
        start_secs = self.get_time(start_time)
        end_secs = self.get_time(now)
        df = api.get_time_price_series(
            exchange=exchange,
            token=symbol,
            starttime=start_secs,
            endtime=end_secs,
            interval=interval,
        )
        
        # --- VALIDATE ---
        if not df or not isinstance(df, list):
            logger.warning(
                f"No historical data returned for token {symbol}. API response: {df}"
            )
            return pd.DataFrame()
        
        df = pd.DataFrame(df)
        
        # The API returns timestamps in seconds under the 'ssboe' key.
        df["ssboe"] = pd.to_numeric(df["ssboe"], errors="coerce")
        df["time"] = pd.to_datetime(df["ssboe"], unit="s")
        df["time"] = df["time"].dt.tz_localize("UTC").dt.tz_convert(IST)
        
        # Convert OHLC to numeric
        for col in ["into", "inth", "intl", "intc"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        # Clean and process
        df = df.sort_values(by="time", ascending=True).reset_index(drop=True)
        df = df.dropna(subset=["time"])
        
        if not df.empty:
            data_entry = {
                "DateTime": df["time"],  # tz-aware datetime (NOT string)
                "Date": df["time"].dt.date,
                "Time": df["time"].dt.strftime("%H:%M:%S"),
                "Symbol": [symbol] * len(df),
                "Open": df.get("into"),
                "High": df.get("inth"),
                "Low": df.get("intl"),
                "Close": df.get("intc"),
            }
            hist_df = pd.DataFrame(data_entry)
            # Ensure DateTime dtype
            hist_df["DateTime"] = pd.to_datetime(hist_df["DateTime"])  # keeps tz
            return hist_df
        
        return pd.DataFrame()

    def update_realtime_candles(self, symbol, interval=OptionChain_data_interval):
        """Load historical candles once (if merged_df is empty) and update the live candle from LTP.
        
        Call this frequently (e.g., every 1s) from main loop or background updater.
        """
        # 1. Load historical candles ONLY if empty
        if self.merged_df.empty:
            df = self.realtimeCandles(symbol=symbol, days=10, interval=interval)
            if df is not None and not df.empty:
                with self.data_lock:
                    # Append historical candles to buffer as dicts with DateTime as datetime
                    self.rt_buffer.extend(df.to_dict(orient="records"))
            logger.info("Loaded historical candles.")
        
        # 2. Update live candle every call
        self.update_live_candle_from_ltp(symbol, interval)

    def load_historical_data(self, days=10, interval=OptionChain_data_interval):
        """Loads historical data to seed merged_df."""
        try:
            logger.info(f"Loading historical data for {self.symbol}...")
            df = self.realtimeCandles(self.symbol, days=days, interval=interval)
            self._clear_table("option_historical")
            self._clear_table("option_strategy_results")
            if df is not None and not df.empty:
                records = df.to_dict("records")
                self._bulk_insert_historical(records)
                with self.data_lock:
                    self.merged_df = df.copy()
                self.merged_df = (
                    self.merged_df.sort_values(by="DateTime", ascending=True)
                    .reset_index(drop=True)
                )
                if len(self.merged_df) > self.max_bars:
                    self.merged_df = (
                        self.merged_df.iloc[-self.max_bars :]
                        .reset_index(drop=True)
                    )
                logger.info(
                    f"Loaded {len(self.merged_df)} historical bars for {self.symbol}."
                )
            else:
                logger.warning(f"No historical data found for {self.symbol}.")
        except Exception as e:
            logger.exception(f"Error loading historical data for {self.symbol}: {e}")

    def check_and_process_historical_signals(self):
        """
        After historical data is loaded into self.merged_df,
        run Strategy_Indicators to see if the last state implies we
        should be 'in position' (unmatched CALL). If yes and we have no
        current open positions, place CALL immediately.
        """
        if self.merged_df is None or self.merged_df.empty:
            self.logger.warning(
                f"No historical data available for initial signal check on {self.symbol}"
            )
            return

        try:
            signals_df = Strategy_Indicators(self.merged_df, self.in_position)
            if signals_df is None or signals_df.empty:
                self.logger.warning("No signals generated from historical data")
                return

            in_position = False
            unresolved_call_time = None

            trade_actions = signals_df.get("Trade_Action", pd.Series(index=signals_df.index))
            for idx in signals_df.index:
                action = trade_actions.loc[idx]
                if action == "CALL" and not in_position:
                    in_position = True
                    unresolved_call_time = signals_df.loc[idx, "DateTime"]
                elif action == "CALL_EXIT" and in_position:
                    in_position = False
                    unresolved_call_time = None

            if in_position and unresolved_call_time:
                self.logger.info(
                    f"Detected unresolved historical CALL at {unresolved_call_time} for {self.tradingsymbol}"
                )
                positions = get_positions()
                open_positions = [
                    p for p in positions if float(p.get("netqty", 0)) != 0.0
                ]
                if open_positions:
                    self.logger.warning(
                        "Open positions already exist. Skipping historical CALL entry."
                    )
                    self.in_position = True
                    return

                available_balance = get_available_balance()
                ltp = get_ltp(self.symbol)
                total_cost = self.lot_size * ltp
                quantity = available_balance // total_cost

                if quantity > 0:
                    lots = quantity * 75
                    try:
                        place_order(
                            option_row={
                                "tradingsymbol": self.tradingsymbol,
                                "lots": lots,
                            },
                            action="CALL"
                        )
                        self.logger.info(
                            f"Historical CALL order placed: {self.tradingsymbol} - {lots} lots"
                        )
                        self.in_position = True
                    except Exception as e:
                        self.logger.exception(
                            f"Failed to place historical CALL order for {self.tradingsymbol}: {e}"
                        )
                else:
                    self.logger.warning(
                        f"Insufficient balance for historical CALL entry. "
                        f"Available={available_balance}, Required={total_cost}"
                    )
                    self.logger.error(
                        f"🛑 Stopping monitor for {self.symbol} due to insufficient balance. "
                        f"Cannot place historical CALL entry."
                    )
                    stop_option_monitor(self.symbol, self.tradingsymbol)
                    return
            else:
                self.logger.info("No unresolved historical CALL signal found.")
                self.in_position = False

        except Exception as e:
            self.logger.exception(
                f"Error during historical signal check for {self.symbol}: {e}"
            )

    def run(self) -> None:
        """
        Continuous monitoring loop:
        1. Select option (with PCR/gamma validation)
        2. Enter position
        3. Monitor for exit
        4. Exit position
        5. Check for EXIT signal from StrategyData
        6. If no EXIT → Loop back to step 1 (re-entry)
        """
        while not self.stop_event.is_set():
            try:
                # STEP 1: Select option (with PCR/gamma validation)
                self.logger.info(f"🔍 Selecting best {self.signal_type} option...")
                if not self.select_and_initialize_option():
                    self.logger.warning("Option selection failed, retrying in 5s...")
                    time.sleep(5)
                    continue
                
                # STEP 2: Load historical data for selected option
                self.load_historical_data(days=10, interval=1)
                
                # STEP 3: Check and process historical signals (potential immediate entry)
                self.check_and_process_historical_signals()
                
                # STEP 4: Monitor until exit signal
                while not self.stop_event.is_set() and not check_strategy_exit_signal(self.signal_type):
                    self.merge_buffers()
                    
                    if self.merged_df is None or self.merged_df.empty:
                        logging.debug("Merged DataFrame empty, sleeping...")
                        self.stop_event.wait(1)
                        continue

                    # Generate signals from merged data (candles updated by background thread)
                    final_df = Strategy_Indicators(self.merged_df, self.in_position, enable_gamma=True, signal_type=self.signal_type)
                    if final_df is None or final_df.empty:
                        logger.warning("No data available from Strategy_Indicators")
                        time.sleep(1)
                        continue
                    
                    latest_row = final_df.iloc[-1]
                    trade_action = latest_row.get("Trade_Action")
                    signal_time = pd.to_datetime(latest_row.get("DateTime"))
                    signal_close = latest_row.get("Close")
                    
                    # Post-market cleanup
                    if signal_time.time() >= datetime.time(15, 20):
                        self.logger.info("Market close approaching, stopping monitor")
                        self.stop_event.set()
                        break

                    # --- STOP LOSS MONITOR ---
                    if self.in_position and getattr(self, "current_stop_loss", None):
                        ltp = get_ltp(self.symbol)
                        sl_hit = False
                        if self.signal_type == "CALL" and ltp < self.current_stop_loss:
                            sl_hit = True
                        elif self.signal_type == "PUT" and ltp > self.current_stop_loss:
                            sl_hit = True
                        
                        if sl_hit:
                            self.logger.warning(f"🛡️ STOP LOSS HIT! LTP: {ltp}, SL: {self.current_stop_loss} - EXITING NOW")
                            # Force overwrite trade_action to trigger exit below
                            trade_action = f"{self.signal_type}_EXIT"
                            # Inject reason 
                            final_df.iloc[-1, final_df.columns.get_loc("EXIT_REASON")] = "STOP_LOSS_HIT"
                            latest_row = final_df.iloc[-1] # Reload latest row to capture reason

                    # ENTRY LOGIC (only if not in position)
                    if trade_action == "CALL" and not self.in_position:
                        available_balance = get_available_balance()
                        self.lot_size = 75
                        symbol = self.symbol
                        ltp = get_ltp(symbol)
                        
                        # --- STRATEGY 2: Reality Check Filter (Smart Order Placement) ---
                        # Prevent entering if price has already crashed (fake-out) or run away too far
                        if ltp and signal_close:
                            # Check 1: Price Rejection (LTP dropped significantly below signal close)
                            if ltp < signal_close * config.REALITY_CHECK_DROP_PCT:  # 0.2% drop
                                self.logger.warning(f"🛑 Reality Check Failed: Price rejected (LTP {ltp} < Signal {signal_close}) - Skipping Entry")
                                continue
                            
                            # Check 2: Price Runaway (LTP moved too far up)
                            if ltp > signal_close * config.REALITY_CHECK_RISE_PCT:  # 0.5% jump
                                self.logger.warning(f"🛑 Reality Check Failed: Price ran away (LTP {ltp} > Signal {signal_close}) - Skipping Entry")
                                continue
                        
                        # Check if this is a gamma-based signal with confidence data
                        gamma_confidence = latest_row.get('GAMMA_CONFIDENCE')
                        
                        # Capture STOP LOSS from signal + Protection
                        self.current_stop_loss = latest_row.get("STOP_LOSS")
                        if not self.current_stop_loss or pd.isna(self.current_stop_loss):
                             # Fallback: 5% default
                             self.current_stop_loss = ltp * 0.95 if trade_action=="CALL" else ltp * 1.05
                             self.logger.warning(f"⚠️ Fallback STOP_LOSS used: {self.current_stop_loss}")
                        else:
                             self.logger.info(f"🛡️ Entry STOP LOSS Set: {self.current_stop_loss}")

                        # Dynamic position sizing based on signal source
                        if gamma_confidence and gamma_confidence > 0:
                            if gamma_confidence > config.GAMMA_CONFIDENCE_HIGH:
                                size_reduction = 0.7
                            else:
                                size_reduction = 0.75
                            
                            self.logger.info(
                                f"📊 GAMMA CALL Signal (confidence: {gamma_confidence:.2f}) - "
                                f"Reducing position size by {(1-size_reduction)*100:.0f}%"
                            )
                            total_cost = self.lot_size * ltp
                            quantity = (available_balance * size_reduction) // total_cost
                        else:
                            total_cost = self.lot_size * ltp
                            quantity = available_balance // total_cost

                        if quantity > 0:
                            lots = int(quantity * 75)
                            place_order(
                                option_row={
                                    "tradingsymbol": self.tradingsymbol,
                                    "lots": lots,
                                },
                                action="CALL"
                            )
                            self.in_position = True
                        else:
                            self.logger.warning("Insufficient balance for CALL entry")
                    
                    # PUT ENTRY LOGIC (only if not in position)
                    elif trade_action == "PUT" and not self.in_position:
                        available_balance = get_available_balance()
                        self.lot_size = 75
                        symbol = self.symbol
                        ltp = get_ltp(symbol)
                        
                        # --- STRATEGY 2: Reality Check Filter (Smart Order Placement) ---
                        # Prevent entering if price has already crashed (fake-out) or run away too far
                        if ltp and signal_close:
                            # Check 1: Price Rejection (LTP dropped significantly below signal close)
                            if ltp < signal_close * config.REALITY_CHECK_DROP_PCT:  # 0.2% drop
                                self.logger.warning(f"🛑 Reality Check Failed: Price rejected (LTP {ltp} < Signal {signal_close}) - Skipping Entry")
                                continue
                            
                            # Check 2: Price Runaway (LTP moved too far up)
                            if ltp > signal_close * config.REALITY_CHECK_RISE_PCT:  # 0.5% jump
                                self.logger.warning(f"🛑 Reality Check Failed: Price ran away (LTP {ltp} > Signal {signal_close}) - Skipping Entry")
                                continue
                        
                        # Check if this is a gamma-based signal with confidence data
                        gamma_confidence = latest_row.get('GAMMA_CONFIDENCE')
                        
                        # Capture STOP LOSS from signal + Protection
                        self.current_stop_loss = latest_row.get("STOP_LOSS")
                        if not self.current_stop_loss or pd.isna(self.current_stop_loss):
                             # Fallback: 5% default
                             self.current_stop_loss = ltp * 1.05  # PUT stop is higher
                             self.logger.warning(f"⚠️ Fallback STOP_LOSS used: {self.current_stop_loss}")
                        else:
                             self.logger.info(f"🛡️ Entry STOP LOSS Set: {self.current_stop_loss}")

                        # Dynamic position sizing based on signal source
                        if gamma_confidence and gamma_confidence > 0:
                            if gamma_confidence > config.GAMMA_CONFIDENCE_HIGH:
                                size_reduction = 0.7
                            else:
                                size_reduction = 0.75
                            
                            self.logger.info(
                                f"📊 GAMMA PUT Signal (confidence: {gamma_confidence:.2f}) - "
                                f"Reducing position size by {(1-size_reduction)*100:.0f}%"
                            )
                            total_cost = self.lot_size * ltp
                            quantity = (available_balance * size_reduction) // total_cost
                        else:
                            total_cost = self.lot_size * ltp
                            quantity = available_balance // total_cost

                        if quantity > 0:
                            lots = int(quantity * 75)
                            place_order(
                                option_row={
                                    "tradingsymbol": self.tradingsymbol,
                                    "lots": lots,
                                },
                                action="PUT"
                            )
                            self.in_position = True
                        else:
                            self.logger.warning("Insufficient balance for PUT entry")
                    
                    # EXIT LOGIC (check both flag AND actual positions)
                    elif trade_action in ["CALL_EXIT", "PUT_EXIT"]:
                        self.logger.info(f"🚪 {trade_action} signal detected at {signal_time}")
                        self.logger.debug(f"Internal position flag: {self.in_position}")
                        
                        positions = get_positions()
                        open_positions = [
                            p for p in positions 
                            if float(p.get("netqty", 0)) != 0.0 and p.get("tsym") == self.tradingsymbol
                        ]
                        
                        if open_positions:
                            self.logger.info(f"📤 Exiting {len(open_positions)} position(s)")
                            for position in open_positions:
                                exit_option = {
                                    "tradingsymbol": position.get("tsym"),
                                    "symbol": position.get("tsym"),
                                    "exit_time": signal_time,
                                    "exit_reason": latest_row.get("EXIT_REASON"),
                                    "netqty": position.get("netqty"),
                                }
                                try:
                                    self.logger.info(f"📤 Placing EXIT order for {position.get('tsym')}, qty: {position.get('netqty')}, reason: {latest_row.get('EXIT_REASON')}")
                                    place_order(option_row=exit_option, action="EXIT")
                                    self.logger.info(f"✅ EXIT order placed successfully")
                                except Exception as e:
                                    self.logger.exception(f"❌ Failed to place exit order: {e}")
                        elif self.in_position:
                            self.logger.warning(f"⚠️ Exit signal but no broker positions found (flag was True)")
                        else:
                            self.logger.debug(f"ℹ️ Exit signal but not in position (skipping)")
                        
                        self.in_position = False
                        self._clear_table("option_historical")
                        self._clear_table("option_strategy_results")
                        break  # Exit inner monitoring loop to re-select option
                    
                    time.sleep(1)
                
                # STEP 5: Check if StrategyData signaled EXIT
                if check_strategy_exit_signal(self.signal_type):
                    self.logger.info("🛑 StrategyData signaled EXIT, stopping monitor completely")
                    self.logger.debug(f"Internal position flag: {self.in_position}")
                    
                    # ✅ FIX: Check ACTUAL broker positions, not just internal flag
                    positions = get_positions()
                    open_positions = [
                        p for p in positions 
                        if float(p.get("netqty", 0)) != 0.0 and p.get("tsym") == self.tradingsymbol
                    ]
                    
                    if open_positions:
                        self.logger.warning(f"⚠️ Found {len(open_positions)} open position(s) - Force exiting")
                        for position in open_positions:
                            exit_option = {
                                "tradingsymbol": position.get("tsym"),
                                "symbol": self.symbol,
                                "exit_time": datetime.datetime.now(),
                                "exit_reason": "Global Strategy Exit",
                                "netqty": position.get("netqty"),
                            }
                            try:
                                self.logger.info(f"📤 Placing EXIT order for {position.get('tsym')}, qty: {position.get('netqty')}")
                                place_order(option_row=exit_option, action="EXIT")
                                self.logger.info(f"✅ EXIT order placed successfully")
                            except Exception as e:
                                self.logger.exception(f"❌ Failed to place exit order: {e}")
                    else:
                        self.logger.info("✅ No open positions found, clean exit")
                    
                    # Reset state
                    self.in_position = False
                    self._clear_table("option_historical")
                    self._clear_table("option_strategy_results")
                    
                    clear_exit_signal(self.signal_type)
                    # Stop the monitor completely - don't loop back
                    self.stop_event.set()
                    return
                
                # STEP 6: Local exit (CALL_EXIT) → Loop back for re-entry
                self.logger.info("♻️ Position closed locally, checking for re-entry...")
                time.sleep(2)
                
            except Exception as e:
                self.logger.exception(f"Error in main loop: {e}")
                time.sleep(5)



if __name__ == "__main__":
    import argparse
    from Shoonya.LoginHelper import login, api

    login()
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal_type", default="CALL", help="CALL or PUT")
    args = parser.parse_args()

    stop_event = threading.Event()
    mon = OptionMonitorRunner(
        stop_event=stop_event,
        signal_type=args.signal_type,
        trial_mode=True,
    )
    try:
        mon.run()
    except KeyboardInterrupt:
        print("\n⚠️ Keyboard interrupt received, stopping...")
        stop_event.set()
