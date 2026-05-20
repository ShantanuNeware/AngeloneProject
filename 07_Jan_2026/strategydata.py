import datetime
import time
from typing import Dict, Optional
import pandas as pd
import logging
from collections import deque
from database.db_writer import enqueue as db_enqueue
from OptionMonitorRunner import (
    OptionMonitorRunner,
    start_option_monitor,
    stop_option_monitor,
    signal_exit_to_monitors,
)
from utils import (
    get_positions,
    get_available_balance,
    place_order,
)
from Shoonya.LoginHelper import login, api
import threading
from Strategy import Strategy_Indicators, generate_trade_signals, check_historical_signals
from config import historical_data_interval


# Timezone for India (IST)
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(threadName)s %(levelname)s: %(message)s",
)

logger = logging.getLogger(__name__)


class StrategyRunner:
    """
    Event-driven strategy runner.
    NO infinite loops.
    NO historical blocking.
    OptionMonitor can start immediately.
    """

    def __init__(
        self,
        stop_event: threading.Event,
        ws_manager,
        primary_symbol: Optional[str],
        trial_mode: bool = True,
        max_bars: int = 500,
    ):
        self.stop_event = stop_event
        self.ws_manager = ws_manager
        self.primary_symbol = primary_symbol
        self.trial_mode = trial_mode
        self.max_bars = max_bars

        self.data_lock = threading.Lock()
        self.merged_df = pd.DataFrame()

        self.last_processed_action = None
        self.last_signal_time = None
        
        self.historical_state = None

    # ---------------------------------------------------------
    # HISTORICAL (ONE TIME ONLY)
    # ---------------------------------------------------------
    def load_historical(self, hist_df: pd.DataFrame):
        if hist_df is None or hist_df.empty:
            logger.warning("No historical data provided.")
            return

        with self.data_lock:
            self.merged_df = hist_df.copy()

        # Check historical signals once at load
        self.historical_state = check_historical_signals()
        logger.info(f"Historical state initialized: {self.historical_state}")

        logger.info(f"Historical loaded: {len(self.merged_df)} rows")

    # ---------------------------------------------------------
    # REALTIME PUSH (called externally)
    # ---------------------------------------------------------
    def on_realtime_candle(self, candle: dict):
        """
        Called by realtime updater / OptionMonitor / WebSocket.
        """
        with self.data_lock:
            self.merged_df = pd.concat(
                [self.merged_df, pd.DataFrame([candle])],
                ignore_index=True,
            )

            self.merged_df = (
                self.merged_df
                .drop_duplicates("DateTime", keep="last")
                .sort_values("DateTime")
                .iloc[-self.max_bars :]
                .reset_index(drop=True)
            )

        self.evaluate()  # 🔥 SINGLE PASS ONLY

    # ---------------------------------------------------------
    # STRATEGY CORE (NON-BLOCKING)
    # ---------------------------------------------------------
    def evaluate(self):
        if self.merged_df.empty:
            return

        final_df = Strategy_Indicators(self.merged_df, historical_state=self.historical_state)
        if final_df.empty:
            return

        latest = final_df.iloc[-1]
        action = str(latest.get("Trade_Action", "")).upper().strip()
        signal_time = pd.to_datetime(latest.get("DateTime"))

        if signal_time.tzinfo is None:
            signal_time = signal_time.tz_localize(IST)

        if action == self.last_processed_action and signal_time == self.last_signal_time:
            return  # already handled

        logger.info(f"📍 Strategy signal: {action} @ {signal_time}")

        # -------------------------------------------------
        # ENTRY
        # -------------------------------------------------
        if action in ("CALL", "PUT"):
            self._handle_entry(action, signal_time)

        # -------------------------------------------------
        # EXIT
        # -------------------------------------------------
        elif action in ("CALL_EXIT", "PUT_EXIT"):
            self._handle_exit(action, signal_time)

        self.last_processed_action = action
        self.last_signal_time = signal_time

    # ---------------------------------------------------------
    # ENTRY HANDLER
    # ---------------------------------------------------------
    def _handle_entry(self, action: str, signal_time):
        from OptionMonitorRunner import active_monitors

        monitor_key = f"{action}_monitor"
        if monitor_key in active_monitors:
            logger.debug(f"{action} monitor already active")
            return

        positions = get_positions()
        open_positions = [p for p in positions if float(p.get("netqty", 0)) != 0]

        if open_positions:
            # Log details of open positions for debugging
            position_details = ", ".join([f"{p.get('tsym', 'Unknown')} (Qty: {p.get('netqty', 0)})" for p in open_positions])
            logger.warning(f"⚠️ Cannot start new OptionMonitor for {action} - {len(open_positions)} open position(s) exist: {position_details}")
            logger.info(f"💡 Waiting for existing positions to be closed before starting new {action} monitor.")
            return

        logger.info(f"🚀 Starting OptionMonitor for {action}")
        start_option_monitor(signal_type=action)

    # ---------------------------------------------------------
    # EXIT HANDLER
    # ---------------------------------------------------------
    def _handle_exit(self, action: str, signal_time):
        signal_exit_to_monitors(action)
        
        # Clear historical state on exit to prevent phantom re-entries or stuck state
        if self.historical_state and self.historical_state.get('in_trade'):
             self.historical_state = {'in_trade': False}
             logger.info("Historical state cleared after exit.")

        signal_type = "CALL" if "CALL" in action else "PUT"
        stop_option_monitor(signal_type)

        positions = get_positions()
        open_positions = [p for p in positions if float(p.get("netqty", 0)) != 0]

        for position in open_positions:
            exit_order = {
                "action": "EXIT",
                "tradingsymbol": position.get("tsym"),
                "symbol": position.get("tsym"),
                "exit_time": signal_time,
                "exit_reason": action,
            }
            try:
                place_order(option_row=exit_order, action="EXIT")
            except Exception:
                logger.exception("Exit order failed")

    def _is_within_trading_window(self, dt):
        """Returns True if dt is between 9:15 and 15:15 IST."""
        if isinstance(dt, str):
            dt = pd.to_datetime(dt)
        if dt.tzinfo is None:
            # assume IST if naive
            dt = dt.replace(tzinfo=IST)
        t = dt.astimezone(IST).time()
        return datetime.time(9, 15) <= t <= datetime.time(15, 30)
