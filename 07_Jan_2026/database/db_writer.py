import queue
import threading
import time
import logging
from database.database import db
import pandas as pd

logger = logging.getLogger(__name__)

# Configurable flush interval (seconds)
FLUSH_INTERVAL = 2.0

# Event queue
_event_queue = queue.Queue()
_stop_event = threading.Event()


def enqueue(event):
    """
    Enqueue an event for DB processing.
    Expected format:
    {
        "type": "pcr",
        "payload": {
            "timestamp": "...",
            "pcr": 1.23,
            "prediction": "BULLISH",
            "rows": [...]  # optional
        }
    }
    """
    _event_queue.put(event)


def _process_batch(events):
    for evt in events:
        try:
            if evt["type"] == "pcr":
                p = evt["payload"]
                rows = p.get("rows", [])
                db.insert_pcr(p["pcr"], p["prediction"], p["timestamp"], rows)
                logger.debug(
                    f"Inserted PCR: {p['pcr']} Prediction: {p['prediction']} Rows: {len(rows)}"
                )
            elif evt["type"] == "trade":
                p = evt["payload"]
                db.insert_trade_data(p)
                logger.debug(f"Inserted trade: {p}")
            elif evt["type"] == "signal":
                p = evt["payload"]
                db.insert_signal(p)
                logger.debug(f"Inserted signal: {p}")
            elif evt["type"] == "strategy_results":
                p = evt["payload"]
                df = p.get("df")
                table_name = p.get("table", "strategy_results")
                if isinstance(df, pd.DataFrame) and not df.empty:
                    db.save_results_to_db(df, table=table_name)
                    logger.debug(f"Saved {len(df)} rows to {table_name}")
            elif evt["type"] == "option_tick":
                p = evt["payload"]
                db.insert_option_tick(p["symbol"], p["data"])
                logger.debug(f"Inserted option tick for {p['symbol']}")
            elif evt["type"] == "option_strategy_results":
                p = evt["payload"]
                df = p.get("df")
                table_name = p.get("table", "option_strategy_results")
                if isinstance(df, pd.DataFrame) and not df.empty:
                    db.save_results_to_db(df, table=table_name)
                    logger.debug(f"Saved {len(df)} rows to {table_name}")
            elif evt["type"] == "liquidity":
                p = evt["payload"]
                db.insert_liquidity_pool(p)
                logger.debug(f"Inserted liquidity pool data")
            else:
                logger.warning(f"Unknown event type: {evt['type']}")
        except Exception as e:
            logger.exception(f"Error processing event {evt}: {e}")


def _worker_loop():
    while not _stop_event.is_set():
        try:
            # Collect batch
            batch = []
            try:
                event = _event_queue.get(timeout=FLUSH_INTERVAL)
                batch.append(event)
                while True:
                    try:
                        batch.append(_event_queue.get_nowait())
                    except queue.Empty:
                        break
            except queue.Empty:
                pass

            if batch:
                _process_batch(batch)

        except Exception:
            logger.exception("Unexpected error in DB writer loop")


def start():
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()
    logger.info("DB Writer thread started.")


def stop():
    _stop_event.set()
    logger.info("DB Writer thread stopped.")
