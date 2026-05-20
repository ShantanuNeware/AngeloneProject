from datetime import datetime, timezone, timedelta
import threading
import signal
import sys
import time
import atexit
import pythoncom
import logging
import urllib3
import pandas as pd

# Suppress SSL warnings from third-party NorenRestApiPy library
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import NIFTY_Index_symbol, Month, Year, historical_data_interval
from Shoonya.LoginHelper import login, api
from strategydata import StrategyRunner
from OptionChainRunner import (
    fetch_option_chain_data as fetch_option_chain_raw,
)
from database.db_writer import (
    start as start_db_writer,
    stop as stop_db_writer,
)
from database.database import (
    db,
)

import logging
from utils import event_handler_quote_update
from logging_config import setup_logging

# Initialize centralized logging (writes to logs/ with a timestamped filename)
setup_logging()

logger = logging.getLogger(__name__)

# Global DB lock
db_lock = threading.Lock()

# Shared snapshot store and lock
snapshot_lock = threading.Lock()
latest_option_chain = {"snapshot": None, "expiry": None}

# Stop event shared globally
stop_event = threading.Event()

# Timezone
IST = timezone(timedelta(hours=5, minutes=30))


def safe_db_execute(conn, sql, params=()):
    """Execute DB statements safely with DB lock."""
    with db_lock:
        with conn:
            conn.execute(sql, params)


def fetch_option_chain_updater(
    stop_event: threading.Event, interval: int = 60, max_retries: int = 3
):
    """
    Continuously fetch option chain snapshots and update shared latest_option_chain.
    Retries on failure up to max_retries.
    """
    pythoncom.CoInitialize()
    try:
        last_keep_alive = time.time()
        while not stop_event.is_set():
            retry_count = 0
            snapshot = None
            while retry_count < max_retries and not stop_event.is_set():
                try:
                    snapshot = fetch_option_chain_raw()
                    if snapshot is not None:
                        with snapshot_lock:
                            latest_option_chain["snapshot"] = (
                                snapshot.copy()
                                if hasattr(snapshot, "copy")
                                else snapshot
                            )
                            latest_option_chain["expiry"] = getattr(
                                snapshot, "expiry", None
                            )
                        logger.info("Option chain snapshot updated.")
                        break
                    else:
                        logger.warning(
                            f"Option chain fetch returned None (attempt {retry_count + 1})"
                        )
                except Exception:
                    logger.exception("Exception during option chain fetch")
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(5)

            # Periodically send a keep-alive request to prevent session timeout
            if time.time() - last_keep_alive > 300:  # Every 5 minutes
                try:
                    login()  # Re-login to be safe
                    logger.info("OptionChain thread: Session keep-alive successful.")
                    last_keep_alive = time.time()
                except Exception:
                    logger.exception("OptionChain thread: Session keep-alive failed.")
            if snapshot is None:
                logger.error(
                    f"Failed to fetch option chain after {max_retries} attempts."
                )

            # Sleep in small increments to allow quick shutdown
            for _ in range(int(interval)):
                if stop_event.is_set():
                    break
                time.sleep(1)
    finally:
        pythoncom.CoUninitialize()


def websocket_thread_wrapper(stop_event: threading.Event):
    """
    WebSocket thread wrapper that calls start_websocket with proper pythoncom init/uninit.
    """
    pythoncom.CoInitialize()
    try:
        logger.info("WebSocket thread started.")
        # Assuming start_websocket accepts stop_event argument
    except Exception:
        logger.exception("Exception in WebSocket thread")
    finally:
        pythoncom.CoUninitialize()
        logger.info("WebSocket thread stopped.")


def realtime_updater_thread(stop_event: threading.Event, strategy_runner_instance):
    """
    Fetches real-time quotes, constructs candles, and pushes them to StrategyRunner.
    """
    interval = historical_data_interval
    current_candle = None
    
    pythoncom.CoInitialize()
    try:
        while not stop_event.is_set():
            try:
                # 1. Get Quote
                quote = api.get_quotes(exchange="NFO", token=NIFTY_Index_symbol)
                if not quote or "lp" not in quote:
                    time.sleep(1)
                    continue

                ltp = float(quote["lp"])
                now = datetime.now(tz=IST)
                minute = now.minute
                boundary_minute = (minute // interval) * interval
                candle_time = now.replace(minute=boundary_minute, second=0, microsecond=0)

                # 2. Initialize or Roll Candle
                if current_candle is None or candle_time != current_candle["DateTime"]:
                    # New candle
                    current_candle = {
                        "Symbol": NIFTY_Index_symbol,
                        "DateTime": candle_time,
                        "Date": candle_time.date(),
                        "Time": candle_time.strftime("%H:%M:%S"),
                        "Open": ltp,
                        "High": ltp,
                        "Low": ltp,
                        "Close": ltp,
                    }
                else:
                    # Update existing candle
                    current_candle["High"] = max(current_candle["High"], ltp)
                    current_candle["Low"] = min(current_candle["Low"], ltp)
                    current_candle["Close"] = ltp

                # 3. Push to Runner
                strategy_runner_instance.on_realtime_candle(current_candle.copy())

            except Exception:
                logger.exception("RealtimeCandles thread failed")

            # Sleep a bit to throttl requests (e.g. 1 second)
            time.sleep(1)
            
    finally:
        pythoncom.CoUninitialize()


class TradingSystem:
    class WebSocketManager:
        """A simple manager to ensure the WebSocket is started only once."""

        def __init__(self, stop_event):
            self._ws_thread = None
            self._lock = threading.Lock()
            self.stop_event = stop_event

        def is_running(self):
            return self._ws_thread is not None and self._ws_thread.is_alive()

        def start(self):
            with self._lock:
                if not self.is_running():
                    logger.info(
                        "Signal received. Starting WebSocket thread for the first time."
                    )
                    self._ws_thread = threading.Thread(
                        target=websocket_thread_wrapper,
                        args=(self.stop_event,),
                        name="WebSocket",
                        daemon=True,
                    )
                    self._ws_thread.start()

    def __init__(self):
        self.stop_event = threading.Event()
        self.ws_manager = self.WebSocketManager(self.stop_event)
        self.strategy_runner = StrategyRunner(
            stop_event=self.stop_event,
            ws_manager=self.ws_manager,
            primary_symbol=NIFTY_Index_symbol,
            trial_mode=True,
        )

    def signal_handler(self, sig, frame):
        logger.info("📴 Shutdown signal received, stopping system...")
        self.stop_event.set()
        try:
            stop_db_writer()
        except Exception:
            logger.exception("Error stopping DB writer")
        try:
            db.close()
        except Exception:
            logger.exception("Error closing DB on shutdown")
        sys.exit(0)

    def initialize(self):
        if not login():
            logger.error("❌ Login failed")
            return False

        logger.info("🧹 Clearing DB tables...")
        try:
            db.clear_all_tables()
        except Exception:
            logger.exception("Error clearing DB tables")
            return False
        
        # 🔹 Load historical data once here
        self.hist_df = event_handler_quote_update(
            NIFTY_Index_symbol, 30, historical_data_interval, exchange="NFO"
        )
        if self.hist_df is not None and not self.hist_df.empty:
            # Convert DateTime from string to datetime objects with IST timezone
            self.hist_df["DateTime"] = pd.to_datetime(self.hist_df["DateTime"]).dt.tz_localize(IST)

            logger.info(f"Historical rows fetched: {len(self.hist_df)}")
            db.insert_historical(self.hist_df)
            logger.info("Historical data inserted successfully.")
            
            # PUSH TO STRATEGY RUNNER
            self.strategy_runner.load_historical(self.hist_df)
        else:
            logger.warning("No historical data found or empty DataFrame.")

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        start_db_writer()
        return True

    def run(self):
        if not self.initialize():
            logger.error("System initialization failed, exiting.")
            return

        threads = [
            threading.Thread(
                target=fetch_option_chain_updater,
                args=(self.stop_event, 60),
                name="OptionChain",
                daemon=True,
            ),
            threading.Thread(
                target=realtime_updater_thread,
                args=(
                    self.stop_event,
                    self.strategy_runner,
                ),
                name="RealtimeCandles",
                daemon=True,
            ),
        ]

        for t in threads:
            t.start()

        logger.info("🚀 Trading system started. Press Ctrl+C to stop.")

        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        finally:
            try:
                stop_db_writer()
            except Exception:
                logger.exception("Error stopping DB writer during shutdown")
            try:
                db.close()
                logger.info("Database connection closed.")
            except Exception:
                logger.exception("Error closing DB during shutdown")
            logger.info("✅ System stopped.")


def cleanup():
    try:
        stop_db_writer()
    except Exception:
        logger.exception("Error stopping DB writer during cleanup")
    try:
        db.close()
        logger.info("Database connection closed on exit.")
    except Exception:
        logger.exception("Error during cleanup DB close")


atexit.register(cleanup)


if __name__ == "__main__":
    system = TradingSystem()
    system.run()
