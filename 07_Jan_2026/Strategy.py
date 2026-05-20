import pandas as pd
import numpy as np
import sqlite3
import logging
from datetime import datetime, timedelta

from indicators import (
    mcginley,
    zlema,
    hull_moving_average,
    rsi_indicator,
    detect_divergences,
    get_trading_zones,
    calculate_slope_and_angle,keltner_channels
)
import indicators_config as cfg
from database.db_writer import enqueue as db_enqueue

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def check_historical_signals(db_path="database/trading.db", lookback_hours=24):
    """
    Check strategy_results table for unresolved CALL/PUT signals.
    
    When the system starts, this function scans the recent history to detect
    if there's an existing CALL or PUT signal without a corresponding EXIT signal.
    This allows the system to resume from the correct state.
    
    Args:
        db_path: Path to the SQLite database
        lookback_hours: How many hours back to check for signals
    
    Returns:
        dict: {
            'in_trade': bool,
            'trade_direction': str or None,  # 'CALL' or 'PUT'
            'entry_time': datetime or None,
            'entry_price': float or None
        }
    """
    try:
        conn = sqlite3.connect(db_path)
        # Query recent signals within lookback window
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
        query = """
            SELECT DateTime, Trade_Action, Close, Entry_Price, trade_direction
            FROM strategy_results
            WHERE DateTime >= ?
            ORDER BY DateTime ASC
        """
        df = pd.read_sql(query, conn, params=(cutoff_time.strftime('%Y-%m-%d %H:%M:%S'),), parse_dates=['DateTime'])
        conn.close()
        
        if df.empty:
            logger.info("No historical signals found in database")
            return {'in_trade': False, 'trade_direction': None, 'entry_time': None, 'entry_price': None}
        
        # Scan for unresolved signals
        in_trade = False
        trade_dir = None
        entry_time = None
        entry_price = None
        
        for idx, row in df.iterrows():
            action = row['Trade_Action']
            if pd.isna(action):
                continue
                
            action = str(action).strip()
            
            if action == 'CALL' and not in_trade:
                in_trade = True
                trade_dir = 'CALL'
                entry_time = row['DateTime']
                entry_price = row.get('Entry_Price')
                if pd.isna(entry_price):
                    entry_price = row['Close']
                logger.info(f"Found unresolved CALL signal from {entry_time} at price {entry_price}")
            elif action == 'PUT' and not in_trade:
                in_trade = True
                trade_dir = 'PUT'
                entry_time = row['DateTime']
                entry_price = row.get('Entry_Price')
                if pd.isna(entry_price):
                    entry_price = row['Close']
                logger.info(f"Found unresolved PUT signal from {entry_time} at price {entry_price}")
            elif action == 'CALL_EXIT' and in_trade and trade_dir == 'CALL':
                in_trade = False
                trade_dir = None
                entry_time = None
                entry_price = None
                logger.info("Found CALL_EXIT - position was closed")
            elif action == 'PUT_EXIT' and in_trade and trade_dir == 'PUT':
                in_trade = False
                trade_dir = None
                entry_time = None
                entry_price = None
                logger.info("Found PUT_EXIT - position was closed")
        
        if in_trade:
            logger.warning(f"⚠️ Detected unresolved {trade_dir} position from {entry_time}")
        else:
            logger.info("✅ No unresolved positions found in history")
        
        return {
            'in_trade': in_trade,
            'trade_direction': trade_dir,
            'entry_time': entry_time,
            'entry_price': entry_price
        }
    except Exception as e:
        logger.exception(f"Error checking historical signals: {e}")
        return {'in_trade': False, 'trade_direction': None, 'entry_time': None, 'entry_price': None}


def generate_trade_signals(df: pd.DataFrame, historical_state: dict = None) -> pd.DataFrame:
    """
    Vectorized entry/exit signals + consistent trade_direction state machine.
    
    Args:
        df: DataFrame with OHLC and indicator data
        historical_state: Optional dict from check_historical_signals() to resume state
    """

    # -------------------------
    # STATE MACHINE + ONGOING TRADE
    # -------------------------
    trade_actions = [None] * len(df)
    exit_reasons = [None] * len(df)
    in_trade_list = [False] * len(df)
    trade_dir_list = [None] * len(df)
    entry_price_list = [np.nan] * len(df)

    in_trade = False
    trade_dir = None
    entry_price = np.nan

    # Check for historical state (existing position from database)
    if historical_state and historical_state.get('in_trade', False):
        in_trade = True
        trade_dir = historical_state['trade_direction']
        entry_price = historical_state.get('entry_price', np.nan)
        logger.info(f"📊 Resuming from historical state: {trade_dir} position from {historical_state.get('entry_time')} at price {entry_price}")
    # Fallback: If DataFrame already has trade_direction from previous run
    elif "trade_direction" in df.columns and not df.empty:
        last_dir = df["trade_direction"].iloc[0]
        if last_dir in ["CALL", "PUT"]:
            in_trade = True
            trade_dir = last_dir
            entry_price = df["Entry_Price"].iloc[0]
            logger.debug(f"Using trade_direction from DataFrame: {trade_dir}")

    for i in range(len(df)):
        # Common variables
        close_price = df.at[i, "Close"]
        zlema5 = df.at[i, "ZLEMA5"]
        mcg5 = df.at[i, "MCG5"]
        slope_zlema = df.at[i, "Slope_ZLEMA"]
        slope_mcg = df.at[i, "Slope_MCG"]
        angle_zlema = df.at[i, "Angle_ZLEMA"]
        angle_mcg = df.at[i, "Angle_MCG"]
        zone = df.at[i, "Zone"]
        mcg9 = df.at[i, "MCG9"]

        # --- ENTRY ---
        if not in_trade:
            # CALL ENTRY CONDITIONS
            cond_zlema_gt_mcg = zlema5 > mcg5
            cond_zone_buy_neutral = (zone == "BUY ZONE") or (zone == "NEUTRAL")
            cond_slope_pos = slope_zlema >= 0
            
            # PUT ENTRY CONDITIONS
            cond_zlema_lt_mcg = zlema5 < mcg5
            cond_zone_sell_neutral = (zone == "SELL ZONE") or (zone == "NEUTRAL")
            cond_slope_neg = slope_zlema <= 0


            # CALL ENTRY
            if cond_zlema_gt_mcg and cond_zone_buy_neutral and cond_slope_pos: 
                trade_dir = "CALL"
                in_trade = True
                trade_actions[i] = "CALL"
                entry_price = close_price
                logger.debug(f"✅ CALL ENTRY at {close_price:.2f}")

            # PUT ENTRY
            elif cond_zlema_lt_mcg and cond_zone_sell_neutral and cond_slope_neg:
                trade_dir = "PUT"
                in_trade = True
                trade_actions[i] = "PUT"
                entry_price = close_price
                logger.debug(f"✅ PUT ENTRY at {close_price:.2f}")

        # --- EXIT ---
        else:
            exit_signal = False
            
            # -------------------------------------------------------------------------
            # EXIT LOGIC
            # -------------------------------------------------------------------------
            slope_long = slope_zlema > 0
            slope_short = slope_zlema < 0
            
            # Retrieve previous slope (handle index 0)
            prev_slope_zlema = df.at[i-1, "Slope_ZLEMA"] if i > 0 else 0.0

            # New Condition: "track when zlema5 > mcg5 and is crossed and increasing , and slope is 0 or reducing then exit"
            # Interpretation: If in bullish territory but momentum is fading:
            # 1. Slope is non-positive (<= 0) OR
            # 2. Slope is positive but decreasing (slope < prev_slope)
            slope_reducing_positive = (slope_zlema <= 0) or (slope_zlema < prev_slope_zlema)
            cond_momentum_fade_positive = (zlema5 > mcg5) and slope_reducing_positive
            
            # Interpretation: If in bearish territory but momentum is fading (becoming less negative):
            # 1. Slope is non-negative (>= 0) OR
            # 2. Slope is negative but increasing towards zero (slope > prev_slope)
            slope_increasing_negative = (slope_zlema >= 0) or (slope_zlema > prev_slope_zlema)
            cond_momentum_fade_negative = (zlema5 < mcg5) and slope_increasing_negative

            # Additional conditions for exit
            bearish_div = df.at[i, "Bearish_Div"] == 1
            bullish_div = df.at[i, "Bullish_Div"] == 1
            
            if trade_dir == "CALL":
                # CALL EXIT: Bearish divergence , slope_short , SELL ZONE, when zlema5 < mcg5
                cond_bear_div = bearish_div
                cond_slope_short = slope_short
                cond_sell_zone = (zone == "SELL ZONE")
                cond_zlema_lt_mcg = zlema5 < mcg5
                
                if cond_momentum_fade_positive or slope_short:
                    exit_signal = True
                    exit_reasons[i] = "CALL_EXIT_Signal"
            
            elif trade_dir == "PUT":
                # PUT EXIT: Bullish divergence , slope_long ,BUY ZONE or neutral, when zlema5 > mcg5
                cond_bull_div = bullish_div
                cond_slope_long = slope_long
                cond_buy_zone_neutral = (zone == "BUY ZONE") or (zone == "NEUTRAL")                
                cond_zlema_gt_mcg = zlema5 > mcg5
                
                if cond_momentum_fade_negative or slope_long:
                    exit_signal = True
                    exit_reasons[i] = "PUT_EXIT_Signal"

            if exit_signal:
                trade_actions[i] = f"{trade_dir}_EXIT"
                exit_reasons[i] = "MOMENTUM_LOSS_EXIT"
                in_trade = False
                trade_dir = None
                entry_price = np.nan

        # --- STATE TRACKING ---
        in_trade_list[i] = in_trade
        trade_dir_list[i] = trade_dir  # persistent placeholder
        entry_price_list[i] = entry_price

    # -------------------------
    # UPDATE RESULTS
    # -------------------------
    df["Trade_Action"] = trade_actions
    df["EXIT_REASON"] = exit_reasons
    df["in_trade"] = in_trade_list
    df["trade_direction"] = trade_dir_list
    df["Entry_Price"] = entry_price_list

    return df


def Strategy_Indicators(df: pd.DataFrame, historical_state: dict = None) -> pd.DataFrame:
    """
    Calculates only indicators used for CALL/PUT entries and exits,
    and generates full strategy results.
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

    # -------------------------
    # INDICATORS
    # -------------------------
   
    # Calculate Slope for ZLEMA7 (5 period)
    df["ZLEMA5"] = zlema(df["Close"], period=7)
    df["ZLEMA23"] = zlema(df["Close"], period=23)
    df_slope_zlema = calculate_slope_and_angle(df["ZLEMA5"], period=5)
    df["Slope_ZLEMA"] = df_slope_zlema["Slope"]
    df["Angle_ZLEMA"] = df_slope_zlema["Angle"]

    df["MCG5"] = mcginley(df["Close"], period=7)
    df["MCG9"] = mcginley(df["Close"], period=9)
    df_slope_mcg = calculate_slope_and_angle(df["MCG5"], period=5)
    df["Slope_MCG"] = df_slope_mcg["Slope"]
    df["Angle_MCG"] = df_slope_mcg["Angle"]

    df["HMA5"] = hull_moving_average(df["Close"], period=7)
    df_slope_hma = calculate_slope_and_angle(df["HMA5"], period=5)
    df["Slope_HMA"] = df_slope_hma["Slope"]
    df["Angle_HMA"] = df_slope_hma["Angle"]

    # RSI & Divergences
    df["RSI"] = rsi_indicator(df, cfg.RSI_LENGTH)
    bull_div, bear_div = detect_divergences(df, df["RSI"])
    df["Bullish_Div"] = bull_div.astype(int)
    df["Bearish_Div"] = bear_div.astype(int)

    #KC
    df_kc_envelope = keltner_channels(df,
    length= 14,
    mult = 0.5,
    source= "Close",
    use_exp= True,
    bands_style= "Average True Range",
    atr_length= 7)

    df["KC_Basis"] = df_kc_envelope["KC_Basis"]
    df["KC_Upper"] = df_kc_envelope["KC_Upper"]
    df["KC_Lower"] = df_kc_envelope["KC_Lower"]



    # Trading Zones
    df_zones = get_trading_zones(df)
    df["Zone"] = df_zones["Zone"]

    if isinstance(df.index, pd.DatetimeIndex):
        df["DateTime"] = df.index
    
    # -------------------------
    # TRADE SIGNALS
    # -------------------------
    df = generate_trade_signals(df, historical_state=historical_state)

    # -------------------------
    # BUILD RESULTS
    # -------------------------
    results = pd.DataFrame(
        {
            "DateTime": df["DateTime"],
            "EXIT_REASON": df["EXIT_REASON"].values,
        }
    )
    df_clean = df.drop(columns=["EXIT_REASON"], errors="ignore")
    final_df = df_clean.merge(results, on="DateTime", how="left")
    
    # Enqueue data for the DB writer
    db_enqueue(
        {
            "type": "strategy_results",
            "payload": {
                "df": final_df,
                "table": "strategy_results",
            },
        }
    )

    return final_df


def get_db_connection(db_path="database/trading.db"):
    conn = sqlite3.connect(db_path)
    print(f"Connected to database at {db_path}")
    return conn


def fetch_data_from_db(conn, table="historical"):
    query = f"SELECT datetime, open, high, low, close FROM {table}"
    return pd.read_sql(query, conn, parse_dates=["DateTime"])


def get_latest_data_for_strategy(lookback_days=15):
    with get_db_connection() as conn:
        query = f"SELECT * FROM historical WHERE datetime >= date('now', '-{lookback_days} days')"
        hist_df = pd.read_sql(query, conn, parse_dates=["datetime"])
        rt_df = pd.read_sql("SELECT * FROM realtime", conn, parse_dates=["datetime"])
        combined = (
            pd.concat([hist_df, rt_df])
            .drop_duplicates(subset=["datetime"])
            .sort_values("datetime")
        )
        return combined


def main():
    try:
        with get_db_connection() as conn:
            hist_df = fetch_data_from_db(conn, table="historical")
            dfs = [df for df in [hist_df] if df is not None and not df.empty]
            if not dfs:
                logger.warning("No data to process.")
                return
            combined_df = pd.concat(dfs).sort_values("datetime").reset_index(drop=True)
            
            # Check historical state once
            historical_state = check_historical_signals()
            
            final_df = Strategy_Indicators(combined_df, historical_state=historical_state)
    except Exception as e:
        logger.exception("Main execution failed: %s", e)


if __name__ == "__main__":
    main()
