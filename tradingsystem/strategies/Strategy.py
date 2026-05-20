"""Strategy runner - orchestrates configured strategies and persists results to DB.

This is a lightweight, scalable runner inspired by the 07_Jan_2026/Strategy.py
It does not require pandas; it runs registered strategies via `StrategyManager`
and writes per-cycle strategy state into `MarketDB` (or via `DBWriter`).
"""
import sys
from pathlib import Path

# Add project root to sys.path to allow independent execution
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from tradingsystem.core.strategy_manager import StrategyManager
from tradingsystem.data.db import MarketDB
from tradingsystem.data.db_writer import DBWriter
from tradingsystem.models import Candle, Signal, SignalType

try:
    import pandas as pd
    import numpy as np
except Exception:
    pd = None
    np = None

try:
    from tradingsystem import indicators as ind
except Exception:
    ind = None


class StrategyRunner:
    def __init__(self, strategy_manager: StrategyManager, db: MarketDB, db_writer: Optional[DBWriter] = None):
        self.strategy_manager = strategy_manager
        self.db = db
        self.db_writer = db_writer

    def check_historical_signals(self, lookback_hours: Optional[int] = None) -> Dict[str, Any]:
        """Check recent entries in `strategy_history` for unresolved positions.

        Returns a dict similar to the Jan implementation:
            {'in_trade': bool, 'trade_direction': str|None, 'entry_time': datetime|None, 'entry_price': float|None}
        """
        try:
            
            if lookback_hours:
                cutoff = (datetime.now() - timedelta(hours=int(lookback_hours))).isoformat()
                rows = self.db.fetch_rows(
                    "SELECT timestamp, Trade_Action, Close, Entry_Price FROM strategy_history WHERE timestamp >= ? ORDER BY timestamp ASC",
                    (cutoff,),
                )
            else:
                rows = self.db.fetch_rows(
                    "SELECT timestamp, Trade_Action, Close, Entry_Price FROM strategy_history ORDER BY timestamp ASC"
                )
            if not rows:
                return {'in_trade': False, 'trade_direction': None, 'entry_time': None, 'entry_price': None}

            in_trade = False
            trade_dir = None
            entry_time = None
            entry_price = None

            for row in rows:
                action = (row.get('Trade_Action') or '').strip() if row.get('Trade_Action') else ''
                close = row.get('Close')
                ent = row.get('Entry_Price')
                ts = row.get('timestamp')
                if not action:
                    continue
                if action in ('CALL', 'PUT') and not in_trade:
                    in_trade = True
                    trade_dir = action
                    entry_time = ts
                    entry_price = ent or close
                elif action.endswith('_EXIT') and in_trade:
                    # e.g. CALL_EXIT closes CALL
                    if (action.startswith('CALL') and trade_dir == 'CALL') or (action.startswith('PUT') and trade_dir == 'PUT'):
                        in_trade = False
                        trade_dir = None
                        entry_time = None
                        entry_price = None

            return {'in_trade': in_trade, 'trade_direction': trade_dir, 'entry_time': entry_time, 'entry_price': entry_price}
        except Exception:
            return {'in_trade': False, 'trade_direction': None, 'entry_time': None, 'entry_price': None}

    def fetch_candles_from_db(
        self,
        token: Optional[str] = None,
        limit: int = 500,
        symbol: Optional[str] = None,
        timeframe: str = "1m",
    ) -> List[Candle]:
        """Fetch the latest candles from the candles table for live strategy use."""
        if hasattr(self.db, "get_candle_models"):
            return self.db.get_candle_models(
                token=token,
                limit=limit,
                symbol=symbol,
                timeframe=timeframe,
            )

        rows = self.db.get_candles(token or "", limit=limit)
        candles: List[Candle] = []
        for row in reversed(rows):
            try:
                ts = row[0]
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                candles.append(
                    Candle(
                        symbol=symbol or str(row[6] if len(row) > 6 else token or ""),
                        timeframe=timeframe,
                        timestamp=ts,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=int(row[5] or 0),
                    )
                )
            except Exception:
                continue
        return candles

    def _calculate_live_context(self, candles: List[Candle]) -> Dict[str, Any]:
        if not candles:
            return {"adx": 0.0, "atr": 0.0, "regime": None}

        lookback = candles[-14:] if len(candles) >= 14 else candles
        atr_values = [c.true_range for c in lookback]
        atr = sum(atr_values) / len(atr_values) if atr_values else 0.0

        closes = [c.close for c in lookback]
        if len(closes) >= 2:
            avg_close = sum(closes) / len(closes)
            adx = 30.0 if closes[-1] > avg_close else 15.0
        else:
            adx = 0.0

        close_price = candles[-1].close
        regime_manager = getattr(self.strategy_manager, "regime_manager", None)
        regime = None
        if regime_manager:
            regime = regime_manager.detect_regime(
                candles=candles,
                adx_value=adx,
                atr_value=atr,
                close_price=close_price,
            )

        return {"adx": adx, "atr": atr, "regime": regime}

    def run_live_from_db(
        self,
        token: Optional[str] = None,
        limit: int = 500,
        symbol: Optional[str] = None,
        timeframe: str = "1m",
        persist_indicators: bool = True,
    ) -> Dict[str, Any]:
        """Fetch candles from DB, recalculate indicators, generate and persist live signals."""
        candles = self.fetch_candles_from_db(
            token=token,
            limit=limit,
            symbol=symbol,
            timeframe=timeframe,
        )
        if len(candles) < 2:
            return {"candles": candles, "signal": None, "signals": [], "indicators": None}

        indicators_df = None
        latest_indicators: Dict[str, Any] = {}
        if pd is not None:
            try:
                indicators_df = self.vectorized_analysis(candles, persist=False)
                if indicators_df is not None and not indicators_df.empty:
                    latest_row = indicators_df.iloc[-1].to_dict()
                    latest_indicators = {
                        k: v
                        for k, v in latest_row.items()
                        if not str(k).lower().endswith("signal")
                    }
            except Exception:
                indicators_df = None

        context = self._calculate_live_context(candles)
        regime = context["regime"]
        if regime is None:
            return {"candles": candles, "signal": None, "signals": [], "indicators": indicators_df}

        signals = self.run_and_persist(
            candles=candles[-100:],
            regime=regime,
            adx_value=context["adx"],
            atr_value=context["atr"],
        )
        signal = signals[0] if signals else self.strategy_manager.analyze_market(
            candles=candles[-100:],
            current_regime=regime,
            adx_value=context["adx"],
            atr_value=context["atr"],
        )

        latest = candles[-1]
        state = {
            "timestamp": latest.timestamp,
            "Symbol": symbol or latest.symbol,
            "Open": latest.open,
            "High": latest.high,
            "Low": latest.low,
            "Close": latest.close,
            "Volume": latest.volume,
            "ADX": context["adx"],
            "ATR": context["atr"],
            "Strategy_State": getattr(regime, "value", str(regime)),
            "Trade_Action": (
                signal.signal_type.value
                if signal and getattr(signal, "signal_type", None)
                else SignalType.HOLD.value
            ),
            **latest_indicators,
            **(signal.indicator_values if signal else {}),
        }

        if persist_indicators:
            try:
                if self.db_writer:
                    self.db_writer.enqueue(self.db.save_strategy_state, state)
                else:
                    self.db.save_strategy_state(state)
            except Exception:
                pass

        if signal:
            try:
                if self.db_writer:
                    self.db_writer.enqueue(self.db.save_signal, signal)
                else:
                    self.db.save_signal(signal)
            except Exception:
                pass

        return {
            "candles": candles,
            "signal": signal,
            "signals": signals or ([signal] if signal else []),
            "indicators": indicators_df,
            "adx": context["adx"],
            "atr": context["atr"],
            "regime": getattr(regime, "value", str(regime)),
        }

    def run_and_persist(
        self,
        candles: List[Candle],
        regime: Any,
        adx_value: float = 0.0,
        atr_value: float = 0.0,
    ) -> List[Signal]:
        """Run all active strategies and persist per-strategy state to the DB.

        For each signal generated, a row is saved to `strategy_history` using
        `MarketDB.save_strategy_state`. If a `DBWriter` is provided, writes
        are enqueued to avoid blocking.
        """
        def _save_state(state: Dict[str, Any]) -> None:
            if self.db_writer:
                try:
                    self.db_writer.enqueue(self.db.save_strategy_state, state)
                    return
                except Exception:
                    pass

            try:
                self.db.save_strategy_state(state)
            except Exception:
                pass

        signals = self.strategy_manager.run_all_strategies(
            candles=candles,
            current_regime=regime,
            adx_value=adx_value,
            atr_value=atr_value,
        )

        latest = candles[-1] if candles else None
        timestamp = latest.timestamp.isoformat() if latest and hasattr(latest.timestamp, 'isoformat') else datetime.now().isoformat()

        if not signals:
            if latest:
                _save_state({
                    'timestamp': timestamp,
                    'Symbol': latest.symbol,
                    'Open': latest.open,
                    'High': latest.high,
                    'Low': latest.low,
                    'Close': latest.close,
                    'Volume': latest.volume,
                    'ADX': adx_value,
                    'ATR': atr_value,
                    'Trade_Action': SignalType.HOLD.value,
                    'Strategy_State': getattr(regime, 'value', str(regime)),
                })
            return []

        for sig in signals:
            state = {
                'timestamp': timestamp,
                'Symbol': getattr(sig, 'symbol', '') or (latest.symbol if latest else ''),
                'Open': getattr(latest, 'open', None),
                'High': getattr(latest, 'high', None),
                'Low': getattr(latest, 'low', None),
                'Close': getattr(latest, 'close', None),
                'Volume': getattr(latest, 'volume', None),
                'Trade_Action': getattr(sig, 'signal_type', None).value if getattr(sig, 'signal_type', None) else None,
                'Strategy_State': getattr(sig, 'regime', None),
            }
            # merge indicator values if present
            try:
                iv = getattr(sig, 'indicator_values', {}) or {}
                for k, v in iv.items():
                    state[k] = v
            except Exception:
                pass

            _save_state(state)

        return signals

    def vectorized_analysis(
        self,
        candles: List[Candle],
        historical_state: Optional[dict] = None,
        persist: bool = False,
    ) -> "pd.DataFrame":
        """Produce a pandas DataFrame of indicators and strategy signals.

        - Requires `pandas` to be installed. If not available, raises RuntimeError.
        - Computes common indicators for registered strategies (MA, RSI, BB)
        - Adds per-strategy signal columns (e.g., `ma_signal`, `rsi_signal`, `bb_signal`)
        - If `persist=True`, writes rows into `strategy_history` via `MarketDB.save_strategy_states_batch`
        """
        if pd is None:
            raise RuntimeError("pandas is required for vectorized_analysis; please install it (pip install pandas)")

        if not candles:
            return pd.DataFrame()

        # Build dataframe from candles
        rows = []
        for c in candles:
            rows.append(
                {
                    "DateTime": c.timestamp,
                    "Open": c.open,
                    "High": c.high,
                    "Low": c.low,
                    "Close": c.close,
                    "Volume": c.volume,
                    "Symbol": c.symbol,
                }
            )

        df = pd.DataFrame(rows)
        df["DateTime"] = pd.to_datetime(df["DateTime"])
        df.set_index("DateTime", inplace=True)

        # --- Expanded indicators (ZLEMA, McGinley, Slope/Angle, Divergences) ---
        if ind is not None:
            try:
                # Default periods (can be overridden per-strategy via config mapping)
                default_zlema_period = 14
                default_mcg_period = 14
                slope_period = 5
                rsi_period = 7

                # ZLEMA and McGinley
                df["ZLEMA"] = ind.zlema(df["Close"], period=default_zlema_period)
                df["MCG"] = ind.mcginley(df["Close"], period=default_mcg_period)

                # Slope & Angle for ZLEMA and McGinley
                slope_z = ind.calculate_slope_and_angle(df["ZLEMA"], period=slope_period)
                df["Slope_ZLEMA"] = slope_z["Slope"]
                df["Angle_ZLEMA"] = slope_z["Angle"]
                df["SlopeFlip_ZLEMA"] = slope_z["SlopeFlip"].astype(bool)

                slope_m = ind.calculate_slope_and_angle(df["MCG"], period=slope_period)
                df["Slope_MCG"] = slope_m["Slope"]
                df["Angle_MCG"] = slope_m["Angle"]
                df["SlopeFlip_MCG"] = slope_m["SlopeFlip"].astype(bool)

                # RSI (global) + divergences
                df["RSI"] = ind.rsi_indicator(df, length=rsi_period, source="Close")
                bull_div, bear_div = ind.detect_divergences(df, df["RSI"], pivot_lookback_left=7, pivot_lookback_right=2, max_lookback_bars=60)
                df["Bullish_Div"] = bull_div
                df["Bearish_Div"] = bear_div
            except Exception:
                # non-fatal: continue without expanded indicators
                pass

        # Helpers
        def _get_param(inst, candidates, default=None):
            # check attribute names and inst.config
            for key in candidates:
                if hasattr(inst, key):
                    return getattr(inst, key)
                # try uppercase
                up = key.upper()
                if hasattr(inst, up):
                    return getattr(inst, up)
            # try config
            try:
                cfg = getattr(inst, "config", None)
                if cfg is not None:
                    for key in candidates:
                        if hasattr(cfg, key):
                            return getattr(cfg, key)
                        if hasattr(cfg, key.lower()):
                            return getattr(cfg, key.lower())
            except Exception:
                pass
            return default

        # Compute indicators & strategy columns
        for name, strat in self.strategy_manager.strategies.items():
            lname = name.lower()

            # MA Strategy
            if "ma" in lname or strat.__class__.__name__.lower().startswith("ma"):
                fast = int(_get_param(strat, ["FAST_PERIOD", "fast_period", "fast_ma", "fast"], 9) or 9)
                slow = int(_get_param(strat, ["SLOW_PERIOD", "slow_period", "slow_ma", "slow"], 21) or 21)
                df[f"ma_fast_{name}"] = df["Close"].rolling(window=fast, min_periods=1).mean()
                df[f"ma_slow_{name}"] = df["Close"].rolling(window=slow, min_periods=1).mean()

                cross_up = (df[f"ma_fast_{name}"] > df[f"ma_slow_{name}"]) & (df[f"ma_fast_{name}"].shift(1) <= df[f"ma_slow_{name}"].shift(1))
                cross_down = (df[f"ma_fast_{name}"] < df[f"ma_slow_{name}"]) & (df[f"ma_fast_{name}"].shift(1) >= df[f"ma_slow_{name}"].shift(1))

                df[f"ma_signal_{name}"] = ""
                df.loc[cross_up & (df["Close"] > df[f"ma_fast_{name}" ]), f"ma_signal_{name}"] = "BUY"
                df.loc[cross_down & (df["Close"].shift(1) > df[f"ma_slow_{name}"]), f"ma_signal_{name}"] = "SELL"

            # RSI Strategy
            if "rsi" in lname or strat.__class__.__name__.lower().startswith("rsi"):
                period = int(_get_param(strat, ["RSI_PERIOD", "rsi_period", "RSI", "rsi"], 14) or 14)
                ov = float(_get_param(strat, ["OVERSOLD", "oversold"], 30) or 30)
                ob = float(_get_param(strat, ["OVERBOUGHT", "overbought"], 70) or 70)

                delta = df["Close"].diff()
                gain = delta.clip(lower=0)
                loss = -delta.clip(upper=0)
                avg_gain = gain.rolling(window=period, min_periods=1).mean()
                avg_loss = loss.rolling(window=period, min_periods=1).mean()
                rs = avg_gain / (avg_loss.replace(0, np.nan))
                rsi = 100 - (100 / (1 + rs))
                rsi = rsi.fillna(100).clip(0, 100)
                df[f"rsi_{name}"] = rsi

                recent_low = df["Low"].rolling(window=5, min_periods=1).min()
                recent_high = df["High"].rolling(window=5, min_periods=1).max()
                df[f"rsi_signal_{name}"] = ""
                df.loc[(df[f"rsi_{name}"] < ov) & (df["Close"] > recent_low * 1.01), f"rsi_signal_{name}"] = "BUY"
                df.loc[(df[f"rsi_{name}"] > ob) & (df["Close"] < recent_high * 0.99), f"rsi_signal_{name}"] = "SELL"

            # BB Strategy
            if "bb" in lname or strat.__class__.__name__.lower().startswith("bb"):
                period = int(_get_param(strat, ["BB_PERIOD", "bb_period", "period"], 20) or 20)
                stdev = float(_get_param(strat, ["BB_STDEV", "bb_stdev", "stdev"], 2.0) or 2.0)
                mid = df["Close"].rolling(window=period, min_periods=1).mean()
                std = df["Close"].rolling(window=period, min_periods=1).std().fillna(0)
                df[f"bb_mid_{name}"] = mid
                df[f"bb_upper_{name}"] = mid + (stdev * std)
                df[f"bb_lower_{name}"] = mid - (stdev * std)
                df[f"bb_signal_{name}"] = ""
                prev = df["Close"].shift(1)
                df.loc[(df["Close"] > df[f"bb_upper_{name}"]) & (prev < df[f"bb_upper_{name}"]), f"bb_signal_{name}"] = "BUY"
                df.loc[(df["Close"] < df[f"bb_lower_{name}"]) & (prev > df[f"bb_lower_{name}"]), f"bb_signal_{name}"] = "SELL"

        # Optional persist
        if persist and not df.empty:
            # prepare rows and write via DB or DBWriter
            out_df = df.reset_index()
            # ensure timestamp key exists for MarketDB compatibility
            out_df["timestamp"] = out_df["DateTime"].apply(lambda x: x.isoformat())
            records = out_df.to_dict(orient="records")
            try:
                if self.db_writer:
                    # enqueue batch write
                    try:
                        self.db_writer.enqueue(self.db.save_strategy_states_batch, records)
                    except Exception:
                        self.db.save_strategy_states_batch(records)
                else:
                    self.db.save_strategy_states_batch(records)
            except Exception:
                pass

        return df


# Convenience factory
def create_runner_from_engine(engine) -> StrategyRunner:
    """Build a StrategyRunner from an engine instance (TradingEngine)."""
    return StrategyRunner(engine.strategy_manager, engine.db, getattr(engine, 'db_writer', None))
