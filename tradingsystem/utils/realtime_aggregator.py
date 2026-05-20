from datetime import datetime
import threading
from typing import Callable, Dict, List, Optional
from tradingsystem.data.db import MarketDB


class RealtimeAggregator:
    """Aggregate ticks into timeframe buckets and flush to DB."""

    def __init__(
        self,
        db: MarketDB,
        timeframe_minutes: int = 1,
        candle_callbacks: Optional[List[Callable[[str, dict, bool], None]]] = None,
    ):
        self.db = db
        self.tf = int(timeframe_minutes)
        self._buckets: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._candle_callbacks = list(candle_callbacks or [])

    def add_candle_callback(self, callback: Callable[[str, dict, bool], None]) -> None:
        """Register a callback fired after each live candle DB update."""
        self._candle_callbacks.append(callback)

    def _bucket_start(self, dt: datetime):
        minute = (dt.minute // self.tf) * self.tf
        return dt.replace(minute=minute, second=0, microsecond=0)

    def on_tick(self, tick):
        """
        Tick is broker.websocket.Tick: (symbol_token, ltp, bid, ask, volume, timestamp)
        Build or update in-memory candle, flush when bucket rolls.
        """
        try:
            dt = datetime.fromtimestamp(tick.timestamp)
            token = tick.symbol_token
            ltp = float(tick.ltp or 0.0)
            vol = int(tick.volume or 0)
            if ltp <= 0:
                return

            row = None
            with self._lock:
                b = self._buckets.get(token)
                start = self._bucket_start(dt)
                if b is None or b["timestamp"] != start:
                    # flush old if exists
                    if b:
                        self._persist(token, b, is_closed=True)
                    # start new bucket
                    self._buckets[token] = {
                        "timestamp": start,
                        "open": ltp,
                        "high": ltp,
                        "low": ltp,
                        "close": ltp,
                        "volume": vol,
                    }
                    row = dict(self._buckets[token])
                else:
                    # update bucket
                    b["high"] = max(b["high"], ltp)
                    b["low"] = min(b["low"], ltp)
                    b["close"] = ltp
                    b["volume"] = b.get("volume", 0) + vol
                    row = dict(b)

                if row:
                    self._persist(token, row, is_closed=False)

        except Exception as e:
            print("RealtimeAggregator.on_tick error:", e)

    def _persist(self, token: str, bucket: dict, is_closed: bool) -> None:
        timestamp = bucket["timestamp"].isoformat()
        try:
            self.db.upsert_candle(
                token=token,
                timestamp=timestamp,
                open_price=bucket["open"],
                high=bucket["high"],
                low=bucket["low"],
                close=bucket["close"],
                volume=bucket.get("volume", 0),
            )
        except Exception as e:
            print("RealtimeAggregator candle write error:", e)
            return

        row = {
            "timestamp": timestamp,
            "Symbol": token,
            "Open": bucket["open"],
            "High": bucket["high"],
            "Low": bucket["low"],
            "Close": bucket["close"],
            "Volume": bucket.get("volume", 0),
        }
        for callback in list(self._candle_callbacks):
            try:
                callback(token, row, is_closed)
            except Exception as e:
                print("RealtimeAggregator candle callback error:", e)

    def _flush(self, token: str, bucket: dict):
        self._persist(token, bucket, is_closed=True)

    def flush_all(self):
        with self._lock:
            items = list(self._buckets.items())
            for token, b in items:
                self._flush(token, b)
                del self._buckets[token]
