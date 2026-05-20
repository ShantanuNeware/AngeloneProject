#!/usr/bin/env python3
"""Quick vectorized analysis test: load recent realtime candles and run StrategyRunner.vectorized_analysis
"""
from datetime import datetime
import sys
from pathlib import Path

# Ensure workspace root is on sys.path so `tradingsystem` package imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingsystem.data.db import MarketDB
from tradingsystem.core.regime_manager import RegimeManager
from tradingsystem.core.strategy_manager import StrategyManager, StrategyManagerConfig
from tradingsystem.models.candle import Candle
from tradingsystem.strategies.Strategy import StrategyRunner


def load_recent_realtime_candles(db: MarketDB, limit: int = 500):
    rows = db.fetch_ohlc_data(table="realtime", limit=limit)
    if not rows:
        return []
    rows = list(reversed(rows))  # chronological order
    candles = []
    for r in rows:
        ts = r.get("timestamp")
        if not ts:
            continue
        try:
            ts_dt = datetime.fromisoformat(ts)
        except Exception:
            try:
                from dateutil.parser import parse

                ts_dt = parse(ts)
            except Exception:
                continue
        symbol = r.get("Symbol") or r.get("symbol") or ""
        try:
            open_p = float(r.get("Open") or 0)
            high = float(r.get("High") or 0)
            low = float(r.get("Low") or 0)
            close = float(r.get("Close") or 0)
            volume = int(r.get("Volume") or 0)
        except Exception:
            continue
        candles.append(
            Candle(
                symbol=symbol,
                timeframe="1m",
                timestamp=ts_dt,
                open=open_p,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
    return candles


def main():
    db = MarketDB()
    candles = load_recent_realtime_candles(db, limit=500)
    if not candles:
        print("No realtime candles found. Trying legacy candles table...")
        tokens = db.fetch_rows("SELECT DISTINCT token FROM candles")
        if tokens:
            token = tokens[0].get("token")
            print("Found token:", token)
            raw = db.get_candles(token, limit=500)
            for r in reversed(raw):
                try:
                    ts_dt = datetime.fromisoformat(r[0])
                except Exception:
                    continue
                candles.append(
                    Candle(
                        symbol=token,
                        timeframe="1m",
                        timestamp=ts_dt,
                        open=float(r[1]),
                        high=float(r[2]),
                        low=float(r[3]),
                        close=float(r[4]),
                        volume=int(r[5] or 0),
                    )
                )

    print(f"Loaded {len(candles)} candles")

    rm = RegimeManager()
    sm_config = StrategyManagerConfig(regime_manager=rm)
    sm = StrategyManager(sm_config)
    runner = StrategyRunner(sm, db)

    try:
        df = runner.vectorized_analysis(candles, persist=False)
    except Exception as e:
        print("Error running vectorized_analysis:", e)
        return

    print("DF shape:", getattr(df, 'shape', None))
    if df is None or df.empty:
        print("Resulting DataFrame is empty")
        return

    cols = df.columns.tolist()
    print("Columns:", cols)

    # Detect divergences
    bulls = df[df.get("Bullish_Div", 0) > 0] if "Bullish_Div" in df.columns else None
    bears = df[df.get("Bearish_Div", 0) > 0] if "Bearish_Div" in df.columns else None

    if bulls is not None and not bulls.empty:
        print(f"Bullish divergences found: {len(bulls)}")
        print(bulls.tail(10).to_string())
    else:
        print("No bullish divergences found")

    if bears is not None and not bears.empty:
        print(f"Bearish divergences found: {len(bears)}")
        print(bears.tail(10).to_string())
    else:
        print("No bearish divergences found")


if __name__ == "__main__":
    main()
