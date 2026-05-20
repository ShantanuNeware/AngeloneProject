import os
import csv
from datetime import datetime, timedelta
from typing import Dict
import threading
import time
import pandas as pd
from config import QUANTITY, NIFTY_Index_symbol, Year, Nearest50_100, exchange, Month
from Shoonya.LoginHelper import login, api
import logging

logger = logging.getLogger(__name__)
from config import (
    QUANTITY,
    NIFTY_Index_symbol,
    Year,
    Nearest50_100,
    exchange,
    Month,
    tradingsymbol,
)


def init_login():
    """Explicit login initializer to avoid side-effects at import time."""
    return login()


def event_handler_quote_update(symbol, days, interval, exchange="NFO"):
    now_dt = datetime.now()
    start_dt = now_dt - timedelta(days=days)
    now = now_dt.strftime("%d-%m-%Y %H:%M:%S")
    start_time = start_dt.strftime("%d-%m-%Y %H:%M:%S")
    start_secs = get_time(start_time)
    end_secs = get_time(now)
    df = api.get_time_price_series(
        exchange=exchange,
        token=symbol,
        starttime=start_secs,
        endtime=end_secs,
        interval=interval,
    )
    # --- FIX: Check for empty or invalid API response before creating DataFrame ---
    if not df or not isinstance(df, list):
        logger.warning(
            f"No historical data returned for token {symbol}. API response: {df}"
        )
        return pd.DataFrame()

    df = pd.DataFrame(df)

    # The API returns timestamps in seconds under the 'ssboe' key.
    df["ssboe"] = pd.to_numeric(df["ssboe"], errors="coerce")
    df["time"] = pd.to_datetime(df["ssboe"], unit="s")
    df["time"] = df["time"].dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata")
    # Clean and process
    df = df.sort_values(by="time", ascending=True).reset_index(drop=True)
    df = df.dropna(subset=["time"])
    if not df.empty:
        data_entry = {
            "DateTime": df["time"].dt.strftime("%Y-%m-%d %H:%M:%S"),  # Only date
            "Date": df["time"].dt.strftime("%Y-%m-%d"),  # Only date
            "Time": df["time"].dt.strftime("%H:%M:%S"),  # Only time
            "Symbol": [symbol] * len(df),
            "Open": df.get("into"),
            "High": df.get("inth"),
            "Low": df.get("intl"),
            "Close": df.get("intc"),
        }
        return pd.DataFrame(data_entry)
    elif df.empty:
        print("No data available for the specified period.")
        return pd.DataFrame()


def get_live_quote(exchange: str, token: str):
    quote = api.get_quotes(exchange=exchange, token=token)

    if quote and "lp" in quote:
        live_data = {
            "lp": float(quote.get("lp", 0.0)),
            "v": int(quote.get("v", 0)),
            "bp": float(quote.get("bp", 0.0)),
            "ap": float(quote.get("ap", 0.0)),
        }
        print(live_data)
        return live_data
    else:
        print(
            f"Failed to get quote for {exchange}:{token} or 'lp' not found in response. API Response: {quote}"
        )
        logger.warning(
            f"Failed to get quote for {exchange}:{token}. API Response: {quote}"
        )
        return None


def get_positions() -> list:
    """
    Fetch current open positions from the broker API.
    Returns a list of dicts with fields like 'tsym', 'netqty', etc.
    """

    try:
        positions = api.get_positions()
    except Exception as e:
        logging.error(f"Failed to fetch positions: {e}")
        return []

    if isinstance(positions, pd.DataFrame):
        positions = positions.to_dict(orient="records")
    elif not isinstance(positions, list):
        positions = []

    # print(f"📊 Current open positions: {positions}")
    return positions


def get_available_balance():
    # Returns available balance as float (sum of cash + payin if both available).
    try:
        limits = api.get_limits()
        print(f"Available limits: {limits}")
        if isinstance(limits, dict):
            # Get cash, payin, premium, and brokerage values
            cash_balance = limits.get("cash")
            payin_balance = limits.get("payin")
            premium = limits.get("premium")
            brokerage = limits.get("brokerage")
            
            # Convert premium and brokerage to float (default to 0 if not available)
            premium_amount = float(premium) if premium not in [None, "NA"] else 0.0
            brokerage_amount = float(brokerage) if brokerage not in [None, "NA"] else 0.0
            
            total_balance = 0.0
            
            # Add cash balance if available
            if cash_balance is not None and cash_balance != "NA":
                total_balance += float(cash_balance)
            
            # Add payin balance if available
            if payin_balance is not None and payin_balance != "NA":
                total_balance += float(payin_balance)
            
            # If we have any balance, deduct premium and brokerage
            if total_balance > 0:
                total_balance -= premium_amount
                total_balance -= brokerage_amount
                print(f"💰 Total Available Balance: ₹{total_balance:.2f} (Cash: {cash_balance}, Payin: {payin_balance}, Premium: {premium_amount}, Brokerage: {brokerage_amount})")
                return float(total_balance)
        
        return 0.0  # Return 0.0 if balance is None, "NA", or not found
    except Exception as e:
        print(f"❌ Error fetching available balance: {e}")
        return 0.0


def get_ltp(symbol):
    try:
        quote = api.get_quotes(exchange="NFO", token=symbol)
        return float(quote["lp"]) if quote and "lp" in quote else None
    except Exception as e:
        print(f"Failed to fetch LTP for {symbol}: {e}")
        return None


def get_atm_strike_price(spot_price):
    if spot_price is None:
        return None
    return round(spot_price / 100) * 100 if spot_price else None


def searchscript(exchange, symbol):
    # --- FIX: Add robust checking for API response ---
    try:
        search_result = api.searchscrip(exchange=exchange, searchtext=symbol)
        if (
            search_result
            and "values" in search_result
            and len(search_result["values"]) > 0
        ):
            return search_result["values"][0].get("token")
    except Exception as e:
        logger.error(f"Error in searchscript for '{symbol}': {e}")
    return None
    # --- END FIX ---


def get_nearest_expiry(exchange, month, year):
    try:
        expiry_dates = api.searchscrip(
            exchange=exchange, searchtext=f"NIFTY {month}{year}"
        )
        if expiry_dates and "values" in expiry_dates:
            expiries = sorted(
                set([item["exd"] for item in expiry_dates["values"] if "exd" in item])
            )
            return expiries[0] if expiries else None
    except Exception as e:
        print(f"Failed to fetch expiry dates: {e}")
        return None


def get_time(time_string):
    return time.mktime(time.strptime(time_string, "%d-%m-%Y %H:%M:%S"))


def countdown_timer(seconds, tick_time=None):
    if tick_time:
        print(f"⏰ Tick UTC time: {tick_time.strftime('%H:%M:%S')} - Countdown started")
    else:
        print(f"⏰ Countdown started")

    while seconds > 0:
        mins, secs = divmod(seconds, 60)
        print(f"Time left: {mins:02d}:{secs:02d}", end="\r", flush=True)
        if seconds % 60 == 0:
            keep_alive()
        time.sleep(1)
        seconds -= 1

    print("\n⏳ Countdown complete!")


def keep_alive():
    try:
        # Ping Shoonya API with a harmless request
        print("🔄 Keeping session alive...")
        api.get_limits()  # Or any lightweight call like api.get_profile()
    except Exception as e:
        print(f"⚠️ Session might have expired. Reauthenticating... {e}")
        api.get_limits()


def place_order(option_row=None, action=None):
    """
    Places a position entry or exit order based on current positions and action.
    Entry: no open positions and action in ["CALL", "PUT"]
    Exit: existing position(s) and action in ["CALL_EXIT", "PUT_EXIT", "EXIT"]
    """
    try:
        # --- Get current open positions ---
        positions_result = get_positions()
        if isinstance(positions_result, pd.DataFrame):
            positions_result = positions_result.to_dict(orient="records")
        if positions_result is None or not isinstance(positions_result, list):
            positions_result = []

        lot_size = QUANTITY
        order_payload = None

        # --- EXIT FIRST ---
        if action in ["CALL_EXIT", "PUT_EXIT", "EXIT"]:
            # Consider both long and short positions (non-zero quantity)
            active_positions = [
                pos for pos in positions_result if float(pos.get("netqty", 0)) != 0
            ]
            if not active_positions:
                print(f"⚠️ Action '{action}' ignored — No active positions to exit")
                return None

            print("📊 Existing trade detected — executing exit signal...")
            for pos in active_positions:
                tsym = str(pos.get("tsym", ""))
                tradingsymbol = tsym
                
                # Final LTP check for EXIT (informational only)
                try:
                    live_quote = get_live_quote("NFO", tradingsymbol)
                    if live_quote:
                        exit_ltp = live_quote.get("lp", 0)
                        logger.info(f"📊 EXIT: {tradingsymbol} | Current LTP: ₹{exit_ltp}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not fetch exit LTP: {e}")
                
                order_payload = {
                    "buy_or_sell": "S",
                    "product_type": "M",
                    "exchange": "NFO",
                    "tradingsymbol": tradingsymbol,
                    "quantity": lot_size,
                    "discloseqty": 0,
                    "price_type": "MKT",
                    "retention": "DAY",
                    "remarks": f"auto-{action}",
                    "amo": "NO",
                }
                logger.info(f"📝 Placing EXIT order: {order_payload}")
                ret = api.place_order(**order_payload)

                return ret  # exit after first active position

        # --- ENTRY NEXT ---
        if action in ["CALL", "PUT"]:
            if not positions_result or all(
                float(x.get("netqty", 0)) == 0 for x in positions_result
            ):
                if option_row is None:
                    print("❌ Cannot place entry order: option_row is required")
                    return None

                tradingsymbol = option_row.get("tradingsymbol")
                
                # --- FINAL LTP CHECK BEFORE ENTRY ---
                try:
                    logger.info(f"🔍 Fetching final LTP for {tradingsymbol}...")
                    live_quote = get_live_quote("NFO", tradingsymbol)
                    
                    if not live_quote:
                        logger.error(f"❌ ENTRY REJECTED: Could not fetch live quote for {tradingsymbol}")
                        print(f"❌ ENTRY REJECTED: No live quote available for {tradingsymbol}")
                        return None
                    
                    current_ltp = live_quote.get("lp", 0)
                    
                    # Validate LTP is reasonable
                    if current_ltp <= 0:
                        logger.error(f"❌ ENTRY REJECTED: Invalid LTP (₹{current_ltp}) for {tradingsymbol}")
                        print(f"❌ ENTRY REJECTED: Invalid LTP ₹{current_ltp} for {tradingsymbol}")
                        return None
                    
                    # Log the final confirmed LTP
                    logger.info(f"✅ ENTRY VALIDATED: {tradingsymbol} | Current LTP: ₹{current_ltp} | Volume: {live_quote.get('v', 0):,}")
                    print(f"✅ Final LTP Check: {tradingsymbol} @ ₹{current_ltp}")
                    
                    # Optional: Check if LTP has moved significantly from original selection
                    # (only if original last_price was provided in option_row)
                    original_ltp = option_row.get("last_price")
                    if original_ltp and original_ltp > 0:
                        price_change_pct = ((current_ltp - original_ltp) / original_ltp) * 100
                        if abs(price_change_pct) > 10:  # More than 10% change
                            logger.warning(f"⚠️ Price moved {price_change_pct:+.2f}% since selection (₹{original_ltp} → ₹{current_ltp})")
                            print(f"⚠️ Price change: {price_change_pct:+.2f}% (₹{original_ltp} → ₹{current_ltp})")
                        else:
                            logger.info(f"✓ Price stable: {price_change_pct:+.2f}% change since selection")
                    
                except Exception as e:
                    logger.error(f"❌ ENTRY REJECTED: Error fetching LTP - {e}")
                    print(f"❌ ENTRY REJECTED: Could not validate LTP - {e}")
                    return None

                order_payload = {
                    "buy_or_sell": "B",
                    "product_type": "M",
                    "exchange": "NFO",
                    "tradingsymbol": tradingsymbol,
                    "quantity": lot_size,
                    "discloseqty": 0,
                    "price_type": "MKT",
                    "retention": "DAY",
                    "remarks": f"auto-{action}",
                    "amo": "NO",
                }
                logger.info(f"📝 Placing ENTRY order: {order_payload}")
                ret = api.place_order(**order_payload)
                return ret

        print(f"⚠️ Action '{action}' ignored — No valid conditions met")
        return None

    except Exception as e:
        logger.exception(f"❌ Exception while placing order: {e}")
        return None


logger = logging.getLogger(__name__)


def get_option_chain_df():
    """
    Fetches the option chain for the configured underlying.
    Returns a pandas DataFrame with all strikes (both CE and PE).
    """
    try:
        # --- Step 1: Get live quote ---
        quote_data = api.get_quotes(exchange, NIFTY_Index_symbol)
        if not quote_data or "lp" not in quote_data:
            logger.error(f"Failed to fetch live quote for {NIFTY_Index_symbol}")
            return None

        try:
            spot_price = float(quote_data["lp"])
        except (ValueError, TypeError):
            logger.error(f"Invalid 'lp' value in quote_data: {quote_data.get('lp')}")
            return None
        print(f"Spot Price: {spot_price}")
        if Nearest50_100 and Nearest50_100 > 0:
            spot_price = int(round(spot_price / Nearest50_100) * Nearest50_100)
        else:
            spot_price = int(round(spot_price))

        logger.info(f"Spot Price (rounded): {spot_price}")

        # --- Step 2: Get nearest expiry (pass month/year, not tradingsymbol) ---
        expiry = get_nearest_expiry(exchange, Month, Year)
        if not expiry:
            logger.error("No expiries returned from API")
            return None
        print(f"Expiry: {expiry}")

        # expiry comes like '01-Oct-2025'
        try:
            expiry_dt = datetime.strptime(expiry, "%d-%b-%Y")
        except ValueError:
            logger.warning(f"Expiry format unexpected: {expiry}, using fallback parser")
            # fallback in case Shoonya returns '01OCT25' or similar
            expiry_dt = datetime.strptime(expiry.replace("-", "").upper(), "%d%b%y")

        expiry_fmt = expiry_dt.strftime("%d%b%y").upper()
        logger.info(f"Using expiry: {expiry_fmt}")

        # Try a fallback with formatted option symbol
        formatted_symbol = f"NIFTY{expiry_fmt}C{spot_price}"
        logger.info(f"Retrying with symbol: {formatted_symbol}")
        option_chain = api.get_option_chain(
            exchange=exchange,
            tradingsymbol=formatted_symbol,
            strikeprice=spot_price,
            count=10,
        )
        # print(option_chain)
        if not option_chain or "values" not in option_chain:
            logger.error(f"Still missing 'values' after retry: {option_chain}")
            return None

        print("✅ Option Chain Response OK:", len(option_chain["values"]))
        df = pd.json_normalize(option_chain["values"])
        logger.info(f"Fetched {len(df)} option chain rows successfully")
        print(df)
        return df

    except Exception as e:
        logger.exception(f"Error fetching option chain: {e}")
        return None


def searchscript1(month=None):
    """
    Search for the NIFTY FUT instrument in Shoonya for the given month.
    Example: searchscript1("NOV")
    """
    try:
        # Use passed month or fallback to global Month if defined
        month_text = month or globals().get("Month", "")
        if not month_text:
            logger.warning("⚠️ No month specified for searchscript1()")
            return None

        search_result = api.searchscrip(
            exchange="NFO", searchtext=f"NIFTY {month_text} FUT"
        )

        # Validate API response
        if not (search_result and "values" in search_result):
            logger.warning("No valid results returned from searchscrip()")
            return None

        # Find the exact NIFTY symbol
        for item in search_result["values"]:
            if item.get("symname", "").upper() == "NIFTY":
                print(
                    f"Token: {item.get('token')}, Expiry: {item.get('exd')},Symbol: {item.get('tsym')}"
                )
                return item  # Return full dictionary for NIFTY

        logger.info("ℹ️ NIFTY not found in search results.")
        return None

    except Exception as e:
        logger.error(f"❌ Error in searchscript1: {e}")
        return None
    
def searchscript_for_Expiry(month=None):
    """
    Search for the NIFTY FUT instrument in Shoonya for the given month.
    Example: searchscript1("NOV")
    """
    try:
        # Use passed month or fallback to global Month if defined
        month_text = month or globals().get("Month", "")
        if not month_text:
            logger.warning("⚠️ No month specified for searchscript1()")
            return None

        search_result = api.searchscrip(
            exchange="NFO", searchtext=f"NIFTY {month_text} FUT"
        )

        # Validate API response
        if not (search_result and "values" in search_result):
            logger.warning("No valid results returned from searchscrip()")
            return None

        # Find the exact NIFTY symbol
        for item in search_result["values"]:
            if item.get("symname", "").upper() == "NIFTY":
                print(
                    f"Token: {item.get('token')}, Expiry: {item.get('exd')},Symbol: {item.get('tsym')}"
                )
                return item  # Return full dictionary for NIFTY

        logger.info("ℹ️ NIFTY not found in search results.")
        return None

    except Exception as e:
        logger.error(f"❌ Error in searchscript1: {e}")
        return None

def searchscript_forToken_ltp(token):
    """
    Search for the NIFTY FUT instrument in Shoonya for the given month.
    Example: searchscript1("NOV")
    """
    try:
        search_result = api.searchscrip(
            exchange="NFO", searchtext=token
        )
        print(search_result)
        # Validate API response
        if not (search_result and "values" in search_result):
            logger.warning("No valid results returned from searchscrip()")
            return None

        # Find the exact NIFTY symbol
        for item in search_result["values"]:
            if item.get("symname", "").upper() == "NIFTY":
                print(
                    f"Token: {item.get('token')}, Expiry: {item.get('exd')},Symbol: {item.get('tsym')}"
                )
                return item  # Return full dictionary for NIFTY

        logger.info("ℹ️ NIFTY not found in search results.")
        return None

    except Exception as e:
        logger.error(f"❌ Error in searchscript1: {e}")
        return None

if __name__ == "__main__":
    # --- MODIFICATION: Keep the main thread alive to allow daemon threads to run ---
    logger.info("Starting standalone test for place_order and OptionMonitor...")
    login()
    # get_option_chain_df()
    get_live_quote("NFO","NIFTY09DEC25P25700")
    available_balance = get_available_balance()
    print(f"Available balance: {available_balance}")

