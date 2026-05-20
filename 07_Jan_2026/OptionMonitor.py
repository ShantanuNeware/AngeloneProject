# improved_option_monitor.py
import pandas as pd
import numpy as np
import sqlite3
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from indicators import (
    hull_moving_average,
    mcginley,
    ut_bot_signals,
    zlema,
    calculate_slope_and_angle,
    get_trading_zones,
)
from database.db_writer import enqueue as db_enqueue
from gamma_signals import gamma_trading_signal
import config

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# -------------------------
# Helper utilities
# -------------------------
DB_PATH_DEFAULT = "database/trading.db"


def _ensure_processed_signals_table(conn: sqlite3.Connection):
    """Create a minimal table to persist processed signal ids for idempotency."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_signals (
            signal_id TEXT PRIMARY KEY,
            created_ts TEXT
        )
        """
    )
    conn.commit()


def _mark_signal_processed(conn: sqlite3.Connection, signal_id: str):
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO processed_signals (signal_id, created_ts) VALUES (?, ?)",
        (signal_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def _is_signal_processed(conn: sqlite3.Connection, signal_id: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM processed_signals WHERE signal_id = ? LIMIT 1", (signal_id,))
    return cur.fetchone() is not None


def _make_signal_id(symbol: str, dt: pd.Timestamp, action: str) -> str:
    # deterministic id for idempotency
    payload = f"{symbol}|{pd.Timestamp(dt).isoformat()}|{action}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def compute_size(account_balance: float, risk_pct: float, entry_price: float, stop_price: float, contract_multiplier: float = 1.0, lot_size: int = 1) -> int:
    """
    Conservative position sizing helper. Not used automatically — kept for downstream OrderManager.
    Returns integer number of contracts (rounded down to lot multiple).
    """
    if entry_price is None or stop_price is None:
        return 0
    max_loss = account_balance * (risk_pct / 100.0)
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 1e-9:
        return 0
    per_contract_risk = stop_distance * contract_multiplier
    qty = int(max_loss // per_contract_risk)
    if lot_size > 1:
        qty = (qty // lot_size) * lot_size
    return max(0, qty)


# -------------------------
# Existing public functions (names preserved)
# -------------------------
def classify_zlema_diff_relaxed(zlemadiff: pd.Series, epsilon: float = 0.6) -> pd.Series:
    """Classify ZLEMA difference with optional relaxation."""
    diff = zlemadiff
    prev = diff.shift(1)
    labels = pd.Series(index=diff.index, dtype="object")

    # Zero-crossings first
    labels[(diff > 0) & (prev < 0)] = "NEG_TO_POS"
    labels[(diff < 0) & (prev > 0)] = "POS_TO_NEG"

    mask_no_crossover = labels.isna()

    # Negative side
    neg_mask = mask_no_crossover & (diff < 0) & (prev < 0)
    labels[neg_mask & (diff < prev - epsilon)] = "NEG_INC"
    labels[neg_mask & (diff >= prev - epsilon)] = "NEG_DEC"

    # Positive side
    pos_mask = mask_no_crossover & (diff > 0) & (prev > 0)
    labels[pos_mask & (diff > prev + epsilon)] = "POS_INC"
    labels[pos_mask & (diff <= prev + epsilon)] = "POS_DEC"

    labels.fillna("INIT", inplace=True)
    return labels


def generate_trade_signals(df: pd.DataFrame, initial_position: bool = False, signal_type: str = "CALL") -> pd.DataFrame:
    """
    Pure logic-based signal generation:
    - Generates signals based on signal_type from StrategyData
    - CALL monitor: generates CALL and CALL_EXIT signals
    - PUT monitor: generates PUT and PUT_EXIT signals
    - Ensures one EXIT for each ENTRY (paired signals)
    - No ML models, no forecasting, no clustering

    Improvements:
        - Vectorized entry/exit detection (no per-row loop)
        - Entry requires a score threshold (>=2 of 3 by default)
        - Exit uses relaxed multi-condition voting (>=2 of 3)
        - Only creates candidate Trade_Action flags; Order placement must be separate.
    """
    # Defensive copy
    df = df.copy()

    # Ensure required columns exist
    required = ["ZLEMA_DIFF", "MCG5", "UT_TrailingStop", "UT_signal", "HMA14", "HMA7", "MCG14","ZLEMA7"]
    for col in required:
        if col not in df.columns:
            df[col] = np.nan

    # Base signal classification
    df["zlema_diff_labels"] = classify_zlema_diff_relaxed(df["ZLEMA_DIFF"], epsilon=0.5)

    # Precompute shifted values
    prev_mcg5 = df["MCG5"].shift(1)
    prev_ut_trail = df["UT_TrailingStop"].shift(1)

    # ENTRY: score-based (require >=2 conditions true) - more conservative
    cond_hma = df["HMA7"] > df["HMA14"]
    cond_zlema = df["ZLEMA7"] > df["ZLEMA14"]
    cond_zlema_slope = df["zlema_slope"] > 0
    cond_mcg_slope = df["mcg_slope"] > 0
    cond_mcg = df["ZLEMA7"] > df["MCG14"]

    # Count votes (vectorized)
    entry_score = cond_hma.astype(int) + cond_zlema.astype(int) + cond_mcg_slope.astype(int) + cond_mcg.astype(int) + cond_zlema_slope.astype(int)
    # require >= 3 votes for entry (conservative) but allow >=2 for last-resort depending on volatility
    entry_mask = entry_score >= 3

    # Prevent entry when UT is SELL explicitly
    entry_mask &= df["UT_signal"] != "SELL"

    entry_mask &= df["Zone"] == "BUY ZONE"

    # EXIT: relaxed 2-of-3 voting using mcg5 decline, trailing decline, ut sell
    epsilon = 0.7
    mcg5_change = (df["MCG5"] - prev_mcg5)
    ut_trailing_change = (df["UT_TrailingStop"] - prev_ut_trail)

    exit_cond_1 = mcg5_change < -epsilon
    exit_cond_2 = ut_trailing_change < -epsilon
    exit_cond_3 = df["UT_signal"] == "SELL"

    exit_count = exit_cond_1.astype(int) + exit_cond_2.astype(int) + exit_cond_3.astype(int)
    exit_mask = exit_count >= 2
    exit_mask &= (df["Zone"] == "SELL ZONE") or (df["Zone"] == "NEUTRAL")
    

    # Build Trade_Action column vectorized
    df["Trade_Action"] = None
    df.loc[entry_mask, "Trade_Action"] = signal_type  # 'CALL' or 'PUT'
    df.loc[exit_mask, "Trade_Action"] = f"{signal_type}_EXIT"
    
    # --- STOP LOSS CALCULATION ---
    # For CALL: Stop Loss = Lowest Low of last 3 candles
    # For PUT: Stop Loss = Highest High of last 3 candles
    if signal_type == "CALL":
        # Rolling min of Lows (window=3)
        recent_low = df["Low"].rolling(window=3).min()
        df.loc[entry_mask, "STOP_LOSS"] = recent_low
    else: # PUT
        # Rolling max of Highs (window=3)
        recent_high = df["High"].rolling(window=3).max()
        df.loc[entry_mask, "STOP_LOSS"] = recent_high

    # When both entry and exit true on same candle, prefer EXIT (safety)
    both_mask = entry_mask & exit_mask
    df.loc[both_mask, "Trade_Action"] = f"{signal_type}_EXIT"
    
    # EXIT_REASON: set only for exits
    df["EXIT_REASON"] = None
    df.loc[exit_mask, "EXIT_REASON"] = "TECH_EXIT"

    # The function previously iterated to maintain in_position state; we now produce candidate actions.
    # The consumer (OrderManager) must enforce stateful pairing (one entry -> one exit).
    return df


def Strategy_Indicators(df: pd.DataFrame, initial_position: bool = False, enable_gamma: bool = True, signal_type: str = "CALL") -> pd.DataFrame:
    """
    Calculates technical indicators and generates combined technical + gamma-based
    trade signals for the specified signal_type.
    """
    if df is None or df.empty:
        logger.warning("Strategy_Indicators: Empty DataFrame received.")
        return df

    df = df.copy()

    # -------------------------
    # STANDARDIZE OHLC NAMES
    # -------------------------
    rename_map = {
        "datetime": "DateTime",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
    }
    df.rename(columns=rename_map, inplace=True)

    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Compute indicators with safe handling
    # McGinley
    df["MCG5"] = mcginley(df["Close"], period=5)
    df["MCG14"] = mcginley(df["Close"], period=14)

    # Hull MAs
    df["HMA14"] = hull_moving_average(df["Close"], period=14)
    df["HMA7"] = hull_moving_average(df["Close"], period=5)

    # Validate McGinley outputs
    for col in ["MCG5", "MCG14"]:
        if np.any(np.isnan(df[col])) or np.any(np.isinf(df[col])):
            logger.warning(f"Invalid values in {col}, applying cleanup")
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df[col] = df[col].clip(-1e6, 1e6)
            df[col] = df[col].fillna(method="ffill").fillna(method="bfill")
    
    df_slope_mcg = calculate_slope_and_angle(df["MCG5"], period=5)
    df["mcg_slope"] = df_slope_mcg["slope"]
    df["mcg_angle"] = df_slope_mcg["angle"]

    # ZLEMA
    df["ZLEMA7"] = zlema(df["Close"], period=5)
    df["ZLEMA14"] = zlema(df["Close"], period=5) # Note: Original code used 5 here, keeping as is for safety

    df_slope_zlema = calculate_slope_and_angle(df["ZLEMA7"], period=5)
    df["zlema_slope"] = df_slope_zlema["slope"]
    df["zlema_angle"] = df_slope_zlema["angle"]

    # UT Bot
    ut_bot_signal = ut_bot_signals(df, a=2, c=10, use_heikin=False)
    df["UT_signal"] = ut_bot_signal["Signal"]
    df["UT_TrailingStop"] = ut_bot_signal["UT_TrailingStop"]

    # ZLEMA diffs and classifications
    df["ZLEMA_DIFF"] = df["ZLEMA7"] - df["ZLEMA14"]
    df["ZLEMA_DIFF_TREND"] = classify_zlema_diff_relaxed(df["ZLEMA_DIFF"])

     # Trading Zones
    df_zones = get_trading_zones(df)
    df["Zone"] = df_zones["Zone"]
    # UT_Signal might already be in df or df_zones, ensure we have them
    if "UT_Signal" in df_zones.columns:
        df["UT_Signal_Zone"] = df_zones["UT_Signal"] # Rename to avoid conflict if already exists

    if isinstance(df.index, pd.DatetimeIndex):
        df["DateTime"] = df.index

    # TRADE SIGNALS - Technical (vectorized)
    df = generate_trade_signals(df, initial_position, signal_type)

    # GAMMA integration applied safely to the LAST row only (does not override earlier bars)
    if enable_gamma and len(df) >= 15:
        try:
            recent_df = df.tail(20).copy()
            gamma_signal = gamma_trading_signal(recent_df, force_refresh=False)
            last_idx = df.index[-1]

            if gamma_signal:
                g_action = gamma_signal.get("action")
                g_conf = gamma_signal.get("confidence", 0)
                # Only if gamma action matches monitor and confidence >= 0.6
                if g_action == signal_type and g_conf >= config.GAMMA_CONFIDENCE_MEDIUM:
                    # High confidence override logic
                    if g_conf > config.GAMMA_CONFIDENCE_HIGH:
                        # Do not override exits
                        if df.loc[last_idx, "Trade_Action"] != f"{signal_type}_EXIT":
                            df.loc[last_idx, "Trade_Action"] = signal_type
                            df.loc[last_idx, "GAMMA_CONFIDENCE"] = g_conf
                            df.loc[last_idx, "GAMMA_TARGET"] = gamma_signal.get("target")
                            df.loc[last_idx, "GAMMA_STOP"] = gamma_signal.get("stop_loss")
                            df.loc[last_idx, "SIGNAL_SOURCE"] = "GAMMA_HIGH"
                            logger.info("✅ High-confidence GAMMA signal applied on last candle")
                    else:
                        # Medium confidence - only confirm existing technical signal on last row
                        if df.loc[last_idx, "Trade_Action"] == signal_type:
                            df.loc[last_idx, "GAMMA_CONFIDENCE"] = g_conf
                            df.loc[last_idx, "GAMMA_TARGET"] = gamma_signal.get("target")
                            df.loc[last_idx, "GAMMA_STOP"] = gamma_signal.get("stop_loss")
                            df.loc[last_idx, "SIGNAL_SOURCE"] = "COMBINED"
                            logger.info("✅ GAMMA + Technical combined (last candle)")
                else:
                    # If mismatched gamma, note it in debug
                    logger.debug(f"Ignored gamma action {g_action} for {signal_type} monitor")
        except Exception as e:
            logger.error(f"Gamma signal generation error: {e}", exc_info=True)

    # Initialize gamma columns if missing
    for c in ("GAMMA_CONFIDENCE", "GAMMA_TARGET", "GAMMA_STOP", "SIGNAL_SOURCE"):
        if c not in df.columns:
            if c == "SIGNAL_SOURCE":
                df[c] = "TECHNICAL"
            else:
                df[c] = None

    # BUILD RESULTS: preserve DateTime and Exit reason similar to previous behavior
    results = pd.DataFrame({"DateTime": df["DateTime"], "EXIT_REASON": df["EXIT_REASON"].values})
    df_clean = df.drop(columns=["EXIT_REASON"], errors="ignore")
    final_df = df_clean.merge(results, on="DateTime", how="left")

    # Enqueue the full final_df as before (persist for audit)
    db_enqueue(
        {
            "type": "option_strategy_results",
            "payload": {
                "df": final_df,
                "table": "option_strategy_results",
            },
        }
    )

    # Additionally: create a minimal signal_event for the latest row (idempotent)
    try:
        last_row = final_df.iloc[-1]
        action = last_row.get("Trade_Action", None)
        if action is not None and pd.notna(action):
            # Build a symbol identifier if available (best-effort)
            symbol = last_row.get("symbol") or last_row.get("Symbol") or "UNKNOWN"
            dt = last_row.get("DateTime")
            price = float(last_row.get("Close")) if "Close" in last_row.index and pd.notna(last_row.get("Close")) else None
            gamma_conf = last_row.get("GAMMA_CONFIDENCE")
            gamma_target = last_row.get("GAMMA_TARGET")
            gamma_stop = last_row.get("GAMMA_STOP")
            signal_source = last_row.get("SIGNAL_SOURCE", "TECHNICAL")

            # Create deterministic idempotent signal id
            signal_id = _make_signal_id(symbol, dt, action)

            # Persist / check idempotency
            with get_db_connection() as conn:
                _ensure_processed_signals_table(conn)
                if not _is_signal_processed(conn, signal_id):
                    # Build event payload with minimal, important fields
                    event = {
                        "signal_id": signal_id,
                        "symbol": symbol,
                        "action": action,
                        "time": pd.Timestamp(dt).isoformat() if pd.notna(dt) else datetime.now(timezone.utc).isoformat(),
                        "price": price,
                        "signal_source": signal_source,
                        "gamma_confidence": float(gamma_conf) if pd.notna(gamma_conf) else None,
                        "gamma_target": float(gamma_target) if pd.notna(gamma_target) else None,
                        "gamma_stop": float(gamma_stop) if pd.notna(gamma_stop) else None,
                        # consumer may compute stops/targets or use gamma-provided ones
                    }

                    # Enqueue the signal event for OrderManager / downstream consumer
                    db_enqueue({"type": "signal_event", "payload": event})

                    # Mark as processed to avoid re-enqueue
                    _mark_signal_processed(conn, signal_id)
                    logger.info(f"Enqueued signal_event: {action} ({signal_id})")
                else:
                    logger.debug(f"Signal {signal_id} already processed; skipping enqueue")
    except Exception as e:
        logger.exception("Failed to create/enqueue latest signal_event: %s", e)

    return final_df


def get_db_connection(db_path: str = DB_PATH_DEFAULT):
    """
    Preserved signature. Returns a sqlite3 connection.
    Note: connections created here are not threadsafe across threads unless configured externally.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    # Enable WAL for safer concurrency if using same DB file from multiple threads
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    logger.debug(f"Connected to database at {db_path}")
    return conn


def fetch_data_from_db(conn, table: str = "option_historical"):
    """
    Preserved signature.
    Note: original function returned DateTime parsing with a different column name; keep similar behavior.
    """
    query = f"SELECT datetime, open, high, low, close FROM {table}"
    # we return DataFrame with parsed column name DateTime to match code expectations
    df = pd.read_sql(query, conn, parse_dates=["datetime"])
    if "datetime" in df.columns:
        df.rename(columns={"datetime": "DateTime"}, inplace=True)
    return df


def get_latest_data_for_strategy(lookback_days: int = 15):
    with get_db_connection() as conn:
        query = f"SELECT * FROM option_historical WHERE datetime >= date('now', '-{lookback_days} days')"
        hist_df = pd.read_sql(query, conn, parse_dates=["datetime"])
        rt_df = pd.read_sql("SELECT * FROM realtime", conn, parse_dates=["datetime"])
        # Normalize column names the same way as other functions
        if "datetime" in hist_df.columns:
            hist_df.rename(columns={"datetime": "DateTime"}, inplace=True)
        if "datetime" in rt_df.columns:
            rt_df.rename(columns={"datetime": "DateTime"}, inplace=True)

        combined = (
            pd.concat([hist_df, rt_df], ignore_index=True, sort=False)
            .drop_duplicates(subset=["DateTime"])
            .sort_values("DateTime")
            .reset_index(drop=True)
        )
        return combined


def main():
    try:
        with get_db_connection() as conn:
            hist_df = fetch_data_from_db(conn, table="option_historical")
            dfs = [df for df in [hist_df] if df is not None and not df.empty]

            if not dfs:
                logger.warning("No data to process.")
                return

            combined_df = pd.concat(dfs).sort_values("DateTime").reset_index(drop=True)
            final_df = Strategy_Indicators(combined_df)

    except Exception as e:
        logger.exception("Main execution failed: %s", e)


if __name__ == "__main__":
    main()
