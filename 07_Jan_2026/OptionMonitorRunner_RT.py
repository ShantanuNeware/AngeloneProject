from OptionMonitorRunner import OptionMonitorRunner
import realtime
import logging
import threading
import pandas as pd
import time
from OptionMonitor import Strategy_Indicators

logger = logging.getLogger(__name__)

class OptionMonitorRunner_RT(OptionMonitorRunner):
    """
    Real-Time Version of OptionMonitorRunner.
    Uses WebSocket ticks (via realtime.py) instead of polling APIs.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure realtime socket is started (singleton check inside realtime.py recommended)
        if not realtime.socket_opened:
             threading.Thread(target=realtime.start_websocket, args=(self.stop_event,), daemon=True).start()
             time.sleep(2) # Give it moment to connect

        self.last_processed_time = None

    def update_realtime_candles(self, symbol, interval=1):
        """
        OVERRIDE: Fetch candles from realtime.py's in-memory store
        instead of polling the API.
        """
        # 1. Load historical candles ONLY if empty (Backfill)
        if self.merged_df.empty:
            df = self.realtimeCandles(symbol=symbol, days=10, interval=interval)
            if df is not None and not df.empty:
                with self.data_lock:
                    self.rt_buffer.extend(df.to_dict(orient="records"))
                # Initialize last processed time from history
                if hasattr(df.iloc[-1], 'DateTime'):
                    self.last_processed_time = df.iloc[-1]['DateTime']
            
            logger.info("Loaded historical candles (Backfill).")
            
            # Subscribe to the WebSocket for this symbol now
            realtime.subscribe_symbol(symbol)
            logger.info(f"📡 Subscribed to {symbol} via WebSocket")

        # 2. Sync latest closed candles from realtime.py
        # realtime.ohlc_list stores completed candles: {1: [candle1, candle2...]}
        completed_candles = realtime.ohlc_list[symbol][1] # Get 1-min candles
        
        if completed_candles:
            new_candles = []
            for c in completed_candles:
                c_time = c["timestamp"]
                
                # Skip if already processed
                if self.last_processed_time and c_time <= self.last_processed_time:
                    continue

                c_dict = {
                    "DateTime": c_time,
                    "Date": c_time.date(),
                    "Time": c_time.time().strftime("%H:%M:%S"),
                    "Symbol": symbol,
                    "Open": c["open"],
                    "High": c["high"],
                    "Low": c["low"],
                    "Close": c["close"]
                }
                new_candles.append(c_dict)
                # Update tracker
                if self.last_processed_time is None or c_time > self.last_processed_time:
                    self.last_processed_time = c_time
            
            if new_candles:
                with self.data_lock:
                     self.rt_buffer.extend(new_candles)
                logger.debug(f"Buffered {len(new_candles)} new WebSocket candles")

        # 3. Update LIVE (partial) candle from realtime.py's current state
        # realtime.ohlc_data stores current partial candle: {1: {...}}
        partial = realtime.ohlc_data[symbol][1]
        
        if partial and partial.get("open"): # Check if valid
             # Construct partial candle dict
             self.current_candle = {
                "Symbol": symbol,
                "DateTime": partial["timestamp"], 
                "Open": partial["open"],
                "High": partial["high"],
                "Low": partial["low"],
                "Close": partial["close"]
             }
             # Note: We don't append partial to rt_buffer here, 
             # because Strategy_Indicators usually runs on (Merged DF + Current Candle)
