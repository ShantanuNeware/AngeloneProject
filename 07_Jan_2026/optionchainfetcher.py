# CE/4Oct2025/optionchainfetcher.py
import time
import numpy as np
import pandas as pd
from datetime import datetime, time as dt_time
from scipy.stats import norm
import logging
import re
from Shoonya.LoginHelper import login, api

# Opt-in to future pandas behavior to suppress FutureWarning
pd.set_option('future.no_silent_downcasting', True)

login()

from config import (
    NIFTY_Index_symbol,
    Year,
    Nearest50_100,
    exchange,
    Month,
    CACHE_TTL as CONFIG_CACHE_TTL,
)
from utils import get_live_quote, get_nearest_expiry
from database.db_writer import enqueue as db_enqueue
from database.concurrent_fetch import parallel_map

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.ERROR)

# ⚡ PERFORMANCE SETTING: Toggle between fast Black-Scholes vs API Greeks
# - False: Uses instant Black-Scholes calculation (~0.5s for 30 options)
# - True (default): Uses broker API Greeks (~2-3s for 30 options, more accurate)
USE_API_GREEKS = True  # Using broker API for accurate gamma exposure

# Cache
_cached_option_chain = None
_cached_at = 0

def get_dynamic_cache_ttl():
    """Dynamic cache TTL based on market hours to reduce lag"""
    now = datetime.now().time()
    market_open = dt_time(9, 15)
    market_close = dt_time(15, 30)
    
    if market_open <= now <= market_close:
        return 15.0  # Fast refresh during market hours (reduced lag)
    return 60.0  # Slower refresh outside hours (save API calls)

CACHE_TTL = get_dynamic_cache_ttl()



def calculate_greeks(option_type, S, K, T, r, sigma):
    """Black-Scholes fallback, ensures numeric values even on expiry day"""
    try:
        T = max(T, 1 / 365)  # avoid zero
        sigma = max(sigma, 0.0001)
        S = max(S, 0.001)
        K = max(K, 0.001)

        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        if option_type.lower() == "call":
            delta = norm.cdf(d1)
            theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T))) - r * K * np.exp(
                -r * T
            ) * norm.cdf(d2)
        else:
            delta = norm.cdf(d1) - 1
            theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T))) + r * K * np.exp(
                -r * T
            ) * norm.cdf(-d2)

        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        vega = S * norm.pdf(d1) * np.sqrt(T)

        return {
            "delta": round(float(delta), 4),
            "gamma": round(float(gamma), 4),
            "theta": round(float(theta) / 365, 4),
            "vega": round(float(vega) / 100, 4),
        }
    except Exception as e:
        logger.exception("calculate_greeks error: %s", e)
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}



def detect_liquidity_pools(merged_df):
    """
    Detect liquidity pools (Gamma/Volume Walls).
    
    Returns:
        dict: Liquidity profile with max OI/Vol strikes using underlying spot price.
    """
    if merged_df is None or merged_df.empty:
        return None

    try:
        # Get underlying spot price (same for all rows) 
        # Crucial for determining if strikes are OTM/ITM if needed later
        spot_price = merged_df["underlying_value"].iloc[0]

        # 1. Standing Liquidity (Gamma Walls) - Max OI
        max_ce_oi_row = merged_df.loc[merged_df["oi_CE"].idxmax()]
        max_pe_oi_row = merged_df.loc[merged_df["oi_PE"].idxmax()]

        # 2. Active Liquidity (Hot Zones) - Max Volume
        max_ce_vol_row = merged_df.loc[merged_df["vol_CE"].idxmax()]
        max_pe_vol_row = merged_df.loc[merged_df["vol_PE"].idxmax()]

        # Total Open Interest
        total_ce_oi = int(merged_df["oi_CE"].sum())
        total_pe_oi = int(merged_df["oi_PE"].sum())

        result = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "max_ce_oi_strike": float(max_ce_oi_row["strike"]),
            "max_pe_oi_strike": float(max_pe_oi_row["strike"]),
            "max_ce_vol_strike": float(max_ce_vol_row["strike"]),
            "max_pe_vol_strike": float(max_pe_vol_row["strike"]),
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "spot_price": spot_price
        }
        
        logger.info(f"Liquidity Pools: CE Wall={result['max_ce_oi_strike']}, PE Wall={result['max_pe_oi_strike']}")
        return result
    except Exception as e:
        logger.error(f"Error detecting liquidity pools: {e}")
        return None


def detect_gamma_burst(merged_df, gamma_threshold=0.05, change_factor=1.5):
    """
    Detect potential gamma bursts in the option chain and provide trader-oriented bias.

    Parameters:
        merged_df (pd.DataFrame): Merged CE/PE option chain with greeks and OI.
        gamma_threshold (float): Minimum gamma exposure to consider for burst (not used here, placeholder for advanced logic).
        change_factor (float): Threshold for sudden change in total gamma to classify as 'GAMMA BURST'.

    Returns:
        dict: {
            'signal': str,       # STABLE / ELEVATED / GAMMA BURST
            'strength': float,   # Relative change in gamma from previous snapshot
            'bias': str,         # BULLISH / BEARISH / NEUTRAL based on gamma dominance
            'total_gamma': float,# Net gamma (CE - PE) across near-the-money strikes
            'gamma_ce': float,   # Total CE gamma exposure
            'gamma_pe': float,   # Total PE gamma exposure
            'timestamp': str     # Time of calculation
        }
    """
    if merged_df is None or merged_df.empty:
        # No data to analyze
        return None

    # -------------------------------------
    # 1️⃣ Calculate distance from spot
    # -------------------------------------
    spot = merged_df["underlying_value"].iloc[0]
    merged_df["dist_from_spot"] = (merged_df["strike"] - spot).abs()

    # -------------------------------------
    # 2️⃣ Compute gamma exposure weighted by open interest
    # -------------------------------------
    # Exposure = gamma * OI for CE and PE separately
    merged_df["gamma_exposure_CE"] = merged_df["gamma_CE"] * merged_df["oi_CE"]
    merged_df["gamma_exposure_PE"] = merged_df["gamma_PE"] * merged_df["oi_PE"]

    # Focus on strikes near the spot (±300 points)
    near_df = merged_df[merged_df["dist_from_spot"] <= 300]

    # Total gamma exposure for CE and PE
    total_gamma_ce = near_df["gamma_exposure_CE"].sum()
    total_gamma_pe = near_df["gamma_exposure_PE"].sum()

    # Net total gamma (CE minus PE)
    total_gamma = total_gamma_ce - total_gamma_pe

    # -------------------------------------
    # 3️⃣ Detect burst by comparing with previous total gamma
    # -------------------------------------
    global _prev_total_gamma
    burst_strength = 0
    burst_signal = "STABLE"

    if "_prev_total_gamma" not in globals():
        # First run: initialize previous gamma
        _prev_total_gamma = total_gamma
    else:
        # Relative change in gamma
        change = abs(total_gamma - _prev_total_gamma)
        burst_strength = change / max(
            abs(_prev_total_gamma), 1e-9
        )  # avoid divide by zero

        # Classify burst intensity
        if burst_strength > change_factor:
            burst_signal = "GAMMA BURST"  # Significant sudden move
        elif burst_strength > 0.5:
            burst_signal = "ELEVATED"  # Moderate move
        # Update previous gamma for next snapshot
        _prev_total_gamma = total_gamma

    # -------------------------------------
    # 4️⃣ Trader-oriented directional bias (Market Maker SHORT GAMMA assumption)
    # -------------------------------------
    # Market Makers are SHORT options → SHORT GAMMA → They hedge against price moves
    # 
    # CE gamma dominates (high call OI):
    #   → Price rises → MMs short calls gain delta → MMs SELL to hedge → RESISTANCE
    #   → Interpretation: BEARISH for breakouts (price capped by MM selling)
    # 
    # PE gamma dominates (high put OI):
    #   → Price falls → MMs short puts gain delta → MMs BUY to hedge → SUPPORT  
    #   → Interpretation: BULLISH for dips (price supported by MM buying)
    #
    if total_gamma_ce > total_gamma_pe:
        bias = "BEARISH (CE Gamma Wall → MM hedging creates resistance)"
    elif total_gamma_pe > total_gamma_ce:
        bias = "BULLISH (PE Gamma Wall → MM hedging creates support)"
    else:
        bias = "NEUTRAL (Gamma balanced → Range-bound market)"

    # -------------------------------------
    # 5️⃣ Prepare result dictionary
    # -------------------------------------
    result = {
        "signal": burst_signal,
        "strength": round(burst_strength, 2),
        "bias": bias,
        "total_gamma": round(float(total_gamma), 4),
        "gamma_ce": round(float(total_gamma_ce), 4),
        "gamma_pe": round(float(total_gamma_pe), 4),
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }

    # Log for debugging
    logger.info(f"Gamma Burst Detection: {result}")
    return result


def get_pcr_and_option_data(force_refresh=False, max_workers=12):
    """Fetch option chain, compute PCR, cache results"""
    global _cached_option_chain, _cached_at

    now = time.time()
    if not force_refresh and _cached_option_chain and (now - _cached_at) < CACHE_TTL:
        return _cached_option_chain

    quote_data = get_live_quote(
        "NFO", NIFTY_Index_symbol
    )  # FIX: Index quote is from NSE
    if not quote_data:
        return None, None, None

    spot_price = round(quote_data.get("lp", 0))
    if Nearest50_100:
        spot_price = int(round(spot_price / Nearest50_100) * Nearest50_100)

    expiry = get_nearest_expiry(exchange, Month, Year)
    try:
        expiry_dt = datetime.strptime(expiry, "%d-%b-%Y")
    except:
        return None, None, None

    expiry_fmt = expiry_dt.strftime("%d%b%y").upper()
    formatted_symbol = (
        f"NIFTY{expiry_fmt}C{spot_price if spot_price%100==0 else spot_price:05d}"
    )

    try:
        option_chain = api.get_option_chain(
            exchange=exchange,
            tradingsymbol=formatted_symbol,
            strikeprice=spot_price,
            count=15,
        )
    except:
        return None, None, None
    if not option_chain or "values" not in option_chain:
        return None, None, None

    df_meta = pd.json_normalize(option_chain["values"])
    tsym_list = list(df_meta.get("tsym", []))
    if not tsym_list:
        return None, None, None

    T = max((expiry_dt - datetime.now()).days / 365.0, 1 / 365)
    r = 0.06

    def fetch_quote_and_greeks(tsym):
        try:
            quote = api.get_quotes("NFO", tsym)
            if not quote:
                return None
            option_ltp = float(quote.get("lp", 0))  # Option's Last Traded Price
            K = float(quote.get("strprc", 0))  # Strike Price
            sigma = float(quote.get("iv", 20)) / 100.0  # Implied Volatility
            m = re.search(r"([CP])\d+$", tsym)
            opt_type = "call" if m and m.group(1) == "C" else "put"

            # ⚡ PERFORMANCE OPTIMIZATION: Use instant Black-Scholes calculation
            # CRITICAL: Black-Scholes needs the UNDERLYING spot price (spot_price), 
            # NOT the option's LTP (option_ltp)!
            g = calculate_greeks(opt_type, spot_price, K, T, r, sigma)
            delta, gamma, theta, vega = (
                g["delta"],
                g["gamma"],
                g["theta"],
                g["vega"],
            )

            # Override with API Greeks only if USE_API_GREEKS is True
            if USE_API_GREEKS:
                greeks_df = None
                try:
                    greeks_df = api.option_greek(
                        expiredate=expiry_dt.strftime("%d-%b-%Y").upper(),
                        StrikePrice=str(int(K)),
                        SpotPrice=str(int(spot_price)),  # Use underlying spot price
                        InterestRate=str(r * 100),
                        Volatility=str(sigma * 100),
                        OptionType="CE" if opt_type == "call" else "PE",
                    )
                except:
                    greeks_df = None
                
                if greeks_df:
                    if opt_type == "call":
                        delta = float(greeks_df.get("cal_delta", greeks_df.get("delta", 0)) or 0)
                        gamma = float(greeks_df.get("cal_gamma", greeks_df.get("gamma", 0)) or 0)
                        theta = float(greeks_df.get("cal_theta", greeks_df.get("theta", 0)) or 0)
                        vega = float(greeks_df.get("cal_vega", greeks_df.get("vega", 0)) or 0)
                    else:
                        delta = float(greeks_df.get("put_delta", greeks_df.get("delta", 0)) or 0)
                        gamma = float(greeks_df.get("put_gamma", greeks_df.get("gamma", 0)) or 0)
                        theta = float(greeks_df.get("put_theta", greeks_df.get("theta", 0)) or 0)
                        vega = float(greeks_df.get("put_vega", greeks_df.get("vega", 0)) or 0)

            row = {
                "symbol": tsym,
                "strike": int(K),
                "type": "CE" if opt_type == "call" else "PE",
                "ltp": float(option_ltp),  # Use option_ltp for LTP
                "oi": int(quote.get("oi", 0)),
                "vol": int(quote.get("v", quote.get("volume", 0))),
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "signal": None,
            }

            if (
                row["type"] == "CE"
                and delta > 0.5
                and gamma > 0.02
                and theta > -0.01
                and vega > 0
            ):
                row["signal"] = "BUY CALL"
            elif (
                row["type"] == "PE"
                and delta < -0.5
                and gamma > 0.02
                and theta > -0.01
                and vega > 0
            ):
                row["signal"] = "BUY PUT"
            return row
        except:
            return None

    rows_map = parallel_map(
        fetch_quote_and_greeks, tsym_list, max_workers=max_workers, timeout=3
    )
    rows = [r for r in rows_map.values() if r]
    if not rows:
        return None, None, None

    df_full = pd.DataFrame(rows)
    df_full = df_full.fillna(0).infer_objects(copy=False)
    ce_df = df_full[df_full["type"] == "CE"].copy()
    pe_df = df_full[df_full["type"] == "PE"].copy()

    merged_df = pd.merge(
        ce_df, pe_df, on="strike", how="outer", suffixes=("_CE", "_PE")
    )
    merged_df = merged_df.fillna(0).infer_objects(copy=False)
    merged_df["underlying_value"] = spot_price

    # PCR (Put-Call Ratio) - Industry Standard Interpretation
    total_ce_oi = ce_df["oi"].sum()
    total_pe_oi = pe_df["oi"].sum()
    pcr = round(total_pe_oi / max(total_ce_oi, 1), 2)
    
    # Industry-standard PCR ranges for NIFTY options
    if pcr < 0.5:
        prediction = "OVERBOUGHT (Extreme call buying → potential reversal)"
    elif 0.5 <= pcr < 0.7:
        prediction = "BULLISH (Heavy call activity)"
    elif 0.7 <= pcr < 0.9:
        prediction = "MODERATELY BULLISH"
    elif 0.9 <= pcr <= 1.1:
        prediction = "NEUTRAL (Balanced market)"
    elif 1.1 < pcr <= 1.3:
        prediction = "MODERATELY BEARISH"
    elif 1.3 < pcr <= 1.5:
        prediction = "BEARISH (Heavy put activity)"
    else:  # pcr > 1.5
        prediction = "OVERSOLD (Extreme put buying → potential reversal)"

    _cached_option_chain = (merged_df, pcr, prediction)
    _cached_at = time.time()

    try:
        db_enqueue(
            {
                "type": "pcr",
                "payload": {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "pcr": pcr,
                    "prediction": prediction,
                    "rows": merged_df.to_dict(orient="records"),
                },
            }
        )
        
        # calculate and store liquidity pools
        liquidity = detect_liquidity_pools(merged_df)
        if liquidity:
             db_enqueue({
                "type": "liquidity",
                "payload": liquidity
             })
             
    except:
        pass

    return merged_df, pcr, prediction


def select_best_option(
    merged_df, action, available_balance=None, lot_size_default=75, ltp_col=None
):
    """
    Select ONE best option — but if the first fails affordability/direction,
    automatically try second best, then third best, and so on.

    Returns:
        dict: one matching best option (never None unless no options exist)
    """

    if merged_df is None or merged_df.empty:
        return None

    action = action.upper()
    if action not in ("CALL", "PUT"):
        return None

    spot_price = merged_df["underlying_value"].iloc[0]

    # Build CE or PE dataframe
    if action == "CALL":
        df = merged_df[["symbol_CE", "strike", "ltp_CE", "oi_CE", "vol_CE"]].copy()
        df.rename(
            columns={
                "symbol_CE": "tradingsymbol",
                "ltp_CE": "last_price",
                "oi_CE": "oi",
                "vol_CE": "volume",
            },
            inplace=True,
        )
        df["type"] = "CE"
    else:
        df = merged_df[["symbol_PE", "strike", "ltp_PE", "oi_PE", "vol_PE"]].copy()
        df.rename(
            columns={
                "symbol_PE": "tradingsymbol",
                "ltp_PE": "last_price",
                "oi_PE": "oi",
                "vol_PE": "volume",
            },
            inplace=True,
        )
        df["type"] = "PE"

    df.dropna(subset=["tradingsymbol"], inplace=True)

    df["lotsize"] = lot_size_default
    df["cost_per_lot"] = df["last_price"] * df["lotsize"]
    df["strike_diff"] = (df["strike"] - spot_price).abs()

    # Directional filter (preferred options)
    if action == "CALL":
        preferred = df[df["strike"] >= spot_price]
    else:
        preferred = df[df["strike"] <= spot_price]

    # If no preferred strikes → fallback to all
    if preferred.empty:
        preferred = df.copy()

    # Ranking
    preferred = preferred.sort_values(
        by=["strike_diff", "oi", "volume"], ascending=[True, False, False]
    )

    # Try options one by one until one fits
    skipped_options = []
    for idx, row in preferred.iterrows():
        # Balance check
        if available_balance is not None:
            if row["cost_per_lot"] > float(available_balance):
                skipped_options.append({
                    "symbol": row["tradingsymbol"],
                    "strike": row["strike"],
                    "cost": row["cost_per_lot"],
                    "available": available_balance
                })
                logger.debug(
                    f"⏭️ Skipping {row['tradingsymbol']} (strike={row['strike']}) - "
                    f"Cost={row['cost_per_lot']:.2f} > Available={available_balance:.2f}"
                )
                continue  # try next best

        # VALID OPTION FOUND
        best = row.to_dict()
        best["symbol"] = best.get("tradingsymbol")
        logger.info(
            f"✅ Selected {action} option: {best['tradingsymbol']} "
            f"(strike={best['strike']}, cost={best['cost_per_lot']:.2f})"
        )
        return best

    # If all options fail affordability → return None (not an unaffordable option)
    if skipped_options:
        logger.warning(
            f"❌ No affordable {action} options found. "
            f"Skipped {len(skipped_options)} option(s) due to insufficient balance. "
            f"Available balance: {available_balance:.2f}"
        )
        for opt in skipped_options[:3]:  # Show first 3 skipped options
            logger.warning(
                f"  - {opt['symbol']} @ strike {opt['strike']}: "
                f"Cost={opt['cost']:.2f} > Available={opt['available']:.2f}"
            )
    
    logger.warning(f"❌ No {action} options available in the chain.")
    return None


def main_():
    merged_df, pcr, prediction = get_pcr_and_option_data(force_refresh=True)
    print(f"PCR: {pcr}, Prediction: {prediction}")
    if merged_df is not None:
        print("\nBest CALL:", select_best_option(merged_df, "CALL"))
        print("\nBest PUT:", select_best_option(merged_df, "PUT"))

    gamma_burst = detect_gamma_burst(merged_df)
    print("\nGamma Burst Analysis:", gamma_burst)


if __name__ == "__main__":
    main_()
