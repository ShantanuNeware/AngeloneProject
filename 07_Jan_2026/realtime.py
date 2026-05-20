from Shoonya.LoginHelper import api, login
from config import NIFTY_Index_symbol
from database import insert
from database.database import db
from datetime import datetime, timedelta
import threading
import logging
import time
import signal
import sys
import pandas as pd
from collections import defaultdict
from config import exchange
import queue

strategy_queue = queue.Queue()

login()
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Global variables
symbols = [f"{exchange}|{NIFTY_Index_symbol}"]
timeframes = [1]  # In minutes
ohlc_data = defaultdict(lambda: defaultdict(dict))
ohlc_list = defaultdict(lambda: defaultdict(list))
socket_opened = False
stop_event = threading.Event()
data_lock = threading.Lock()


def get_tf_timestamp(now: datetime, tf: int) -> datetime:
    return now.replace(minute=now.minute - (now.minute % tf), second=0, microsecond=0)


def process_tick(symbol: str, ltp: float):
    now = datetime.now()
    tf = 1  # 1-minute candles
    ts = get_tf_timestamp(now, tf)

    with data_lock:
        current = ohlc_data[symbol][tf]

        if current.get("timestamp") != ts:
            # ✅ Save completed candle to memory
            if current:
                completed_candle = {
                    "timestamp": current["timestamp"],
                    "open": current["open"],
                    "high": current["high"],
                    "low": current["low"],
                    "close": current["close"],
                }
                ohlc_list[symbol][tf].append(completed_candle)
                logger.debug(f"🕯️ Candle closed: {symbol} @ {completed_candle['timestamp']}")

            # Start new candle
            ohlc_data[symbol][tf] = {
                "timestamp": ts,
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
            }
        else:
            # Update existing candle in real-time
            current["high"] = max(current["high"], ltp)
            current["low"] = min(current["low"], ltp)
            current["close"] = ltp



def on_tick_update(message):
    if stop_event.is_set():
        return
    ltp = message.get("lp")
    if ltp:
        print(f"📈 Current LTP: {ltp}")

    if not (ltp_str := message.get("lp")) or float(ltp_str) == 0.0:
        return

    try:
        ltp = float(ltp_str)
        tradingsymbol = f"{message.get('e')}|{message.get('tk')}"
        logger.debug(f"Tick: {tradingsymbol} - LTP: {ltp}")
        process_tick(tradingsymbol, ltp)
    except Exception as e:
        logger.error(f"Tick processing error: {str(e)}")


def on_socket_open():
    global socket_opened
    socket_opened = True
    logger.info("WebSocket connected")
    for symbol in symbols:
        api.subscribe(symbol)
        logger.info(f"Subscribed to: {symbol}")



def start_websocket(stop_event):
    global socket_opened
    if socket_opened:
        logger.info("WebSocket already running.")
        return

    logger.info("Starting WebSocket...")

    try:
        # Connect with correct callbacks
        responce = api.start_websocket(
            subscribe_callback=on_tick_update,
            socket_open_callback=on_socket_open,
            socket_close_callback=lambda: logger.warning("❌ WebSocket closed."),
            socket_error_callback=lambda err: logger.error(
                f"💥 WebSocket error: {err}"
            ),
        )
        
        # Mark as opened if start_websocket returns success (usually happens in callback, but good to track)
        # Note: api.start_websocket might be async or blocking depending on implementation, 
        # but Shoonya usually runs a separate thread internally or blocks. 
        # If it blocks, the loop below is unreachable unless it returns.
        # Assuming typical Shoonya usage where it returns a thread or similar, or we loop to keep main alive.
        
        while not stop_event.is_set():
            logger.debug("📡 Sending ping to keep WebSocket alive...: ")
            logger.info("📡 Heartbeat: WebSocket running... : %s", responce)
            # No send_heartbeat in Shoonya — just log ping
            time.sleep(2)

    except Exception as e:
        logger.error(f"WebSocket failed: {e}")


def signal_handler(sig, frame):
    logger.info("Received shutdown signal")
    stop_event.set()
    try:
        if hasattr(api, "websocket") and api.websocket:
            api.websocket.close()
            logger.info("WebSocket closed")
    except Exception as e:
        logger.error(f"Error closing WebSocket: {e}")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    start_websocket(stop_event)
    time.sleep(2)


