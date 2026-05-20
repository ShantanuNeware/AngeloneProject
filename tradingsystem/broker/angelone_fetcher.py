from datetime import datetime
import logging
import time
import re
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from tradingsystem.models.option import OptionChain, OptionContract, OptionType

logger = logging.getLogger(__name__)


class AngelOneFetcher:
 
    INTERVAL_MAP = {
        "1m": "ONE_MINUTE",
        "5m": "FIVE_MINUTE",
        "15m": "FIFTEEN_MINUTE",
        "1h": "ONE_HOUR",
        "4h": "FOUR_HOUR",
        "1d": "ONE_DAY",
    }

    def __init__(self, client):
        self.client = client

    def fetch(self, token, exchange, interval, start, end, retries: int = 3, backoff: float = 0.5) -> List[Any]:
        """Fetch OHLCV candlestick data.

        - Validates `interval` and falls back to `1m` when unknown.
        - Retries transient failures with exponential backoff.
        - Returns the raw API data list (keeps compatibility).
        """
        # Validate interval mapping
        mapped_interval = self.INTERVAL_MAP.get(interval)
        if not mapped_interval:
            logger.warning("Unknown interval '%s', falling back to 1m", interval)
            mapped_interval = self.INTERVAL_MAP["1m"]

        params = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": mapped_interval,
            "fromdate": start.strftime("%Y-%m-%d %H:%M"),
            "todate": end.strftime("%Y-%m-%d %H:%M"),
        }

        attempt = 0
        while attempt < retries:
            try:
                attempt += 1
                if attempt > 1:
                    logger.info("Retrying fetch (attempt %d/%d)", attempt, retries)

                res = self.client.getCandleData(params)

                if not res:
                    logger.warning("Empty response from getCandleData (attempt %d)", attempt)
                    raise RuntimeError("Empty response from API")

                if not res.get("status"):
                    logger.warning("API returned failure status: %s", res)
                    return []

                data = res.get("data", [])
                if not isinstance(data, list):
                    logger.warning("Unexpected data format from API, expected list")
                    return []

                return data

            except Exception as e:
                logger.error("Fetch error (attempt %d): %s", attempt, e, exc_info=True)
                if attempt >= retries:
                    logger.error("Max retries reached, returning empty list")
                    return []
                # Exponential backoff
                time.sleep(backoff * (2 ** (attempt - 1)))
        # If we exit loop without returning, return empty list
        return []
        
    
    def fetch_option_chain(
        self,
        symbol: str,
        expiry_date: str,
        exchange: str = "NFO"
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch option chain for a symbol and expiry
        
        Args:
            symbol: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
            expiry_date: Expiry date (YYYY-MM-DD format)
            exchange: Exchange code (default: NFO for derivatives)
        
        Returns:
            Option chain data with calls and puts, or None if error
        """
        try:
            params = {
                "exchange": exchange,
                "symbol": symbol,
                "expirydate": expiry_date,
            }
            
            res = self.client.getOptionChain(params)
            
            if not res or not res.get("status"):
                logger.warning(f"Failed to fetch option chain for {symbol} {expiry_date}")
                return None
            
            return res.get("data", {})
        
        except Exception as e:
            logger.error(f"Option chain fetch error: {e}")
            return None
    
    def fetch_option_greeks(
        self,
        symbol: str,
        strike: float,
        expiry_date: str,
        option_type: str = "CE",
        exchange: str = "NFO"
    ) -> Optional[Dict[str, float]]:
        """
        Fetch Greeks (delta, gamma, theta, vega) for an option
        
        Returns: {delta, gamma, theta, vega, iv}
        """
        try:
            params = {
                "exchange": exchange,
                "symbol": symbol,
                "strike": strike,
                "expirydate": expiry_date,
                "optiontype": option_type,  # CE or PE
            }
            
            res = self.client.getOptionGreeks(params)
            
            if not res or not res.get("status"):
                return None
            
            greeks = res.get("data", {})
            return {
                "delta": float(greeks.get("delta", 0.0)),
                "gamma": float(greeks.get("gamma", 0.0)),
                "theta": float(greeks.get("theta", 0.0)),
                "vega": float(greeks.get("vega", 0.0)),
                "iv": float(greeks.get("iv", 0.0)),
            }
        
        except Exception as e:
            logger.error(f"Greeks fetch error: {e}")
            return None

    def get_parsed_option_chain(
        self,
        symbol: str,
        expiry_date: str,
        underlying_price: float = 0.0,
        max_strikes: int = 60,
        use_api_greeks: bool = True,
        max_workers: int = 8,
    ) -> Optional[OptionChain]:
        """
        Fetch option chain and return an OptionChain with parsed OptionContract entries.
        Best-effort extraction that adapts to common broker payload shapes.
        """
        try:
            raw = self.fetch_option_chain(symbol, expiry_date)
            if not raw:
                return None

            tsym_list = []
            # tolerant extraction of trading symbols
            if isinstance(raw, dict):
                if "values" in raw and isinstance(raw["values"], list):
                    for v in raw["values"]:
                        if isinstance(v, dict) and v.get("tsym"):
                            tsym_list.append(v["tsym"])
                        elif isinstance(v, dict) and v.get("tradingsymbol"):
                            tsym_list.append(v["tradingsymbol"])
                        else:
                            tsym_list.append(str(v))
                elif "data" in raw and isinstance(raw["data"], list):
                    for v in raw["data"]:
                        if isinstance(v, dict) and v.get("tradingsymbol"):
                            tsym_list.append(v["tradingsymbol"])
                        elif isinstance(v, dict) and v.get("tsym"):
                            tsym_list.append(v["tsym"])
                elif "tsym" in raw and isinstance(raw["tsym"], list):
                    tsym_list = list(raw["tsym"])
                else:
                    for v in raw.values():
                        if isinstance(v, list):
                            for item in v:
                                if isinstance(item, dict) and item.get("tsym"):
                                    tsym_list.append(item["tsym"])
            elif isinstance(raw, list):
                for v in raw:
                    if isinstance(v, dict) and v.get("tsym"):
                        tsym_list.append(v["tsym"])
                    elif isinstance(v, dict) and v.get("tradingsymbol"):
                        tsym_list.append(v["tradingsymbol"])
                    else:
                        tsym_list.append(str(v))

            tsym_list = [t for t in tsym_list if t][:max_strikes]
            if not tsym_list:
                return None

            # helper: parse strike and option type from trading symbol
            def _parse_tsym(tsym: str):
                m = re.search(r"([CP])(\d+)$", tsym.upper())
                if m:
                    opt = OptionType.CALL if m.group(1) == "C" else OptionType.PUT
                    strike = float(m.group(2))
                    return strike, opt
                nums = re.findall(r"\d+", tsym)
                if nums:
                    strike = float(nums[-1])
                    opt = OptionType.CALL if "C" in tsym.upper() else OptionType.PUT
                    return strike, opt
                return 0.0, OptionType.CALL

            def _build_contract(tsym: str):
                strike, opt_type = _parse_tsym(tsym)
                ltp = 0.0
                bid = 0.0
                ask = 0.0
                volume = 0
                oi = 0
                iv = 0.0
                try:
                    if hasattr(self.client, "getMarketData"):
                        params = {"mode": "FULL", "exchangeTokens": {"NFO": [tsym]}}
                        res = self.client.getMarketData(params)
                        if isinstance(res, dict) and res.get("status"):
                            data = res.get("data", {})
                            quote = None
                            if isinstance(data, list) and data:
                                quote = data[0]
                            elif isinstance(data, dict):
                                for v in data.values():
                                    if isinstance(v, list) and v:
                                        quote = v[0]
                                        break
                                    if isinstance(v, dict):
                                        quote = v
                                        break
                            if isinstance(quote, dict):
                                ltp = float(quote.get("ltp") or quote.get("last_price") or quote.get("lp") or 0.0)
                                bid = float(quote.get("bid") or quote.get("bp") or 0.0)
                                ask = float(quote.get("ask") or quote.get("ap") or 0.0)
                                volume = int(quote.get("v") or quote.get("volume") or 0)
                                oi = int(quote.get("oi") or 0)
                                iv = float(quote.get("iv") or 0.0)
                    elif hasattr(self.client, "getQuotes"):
                        q = self.client.getQuotes("NFO", tsym)
                        if isinstance(q, dict):
                            ltp = float(q.get("lp") or ltp)
                            bid = float(q.get("bp") or bid)
                            ask = float(q.get("ap") or ask)
                            volume = int(q.get("v") or volume)
                            oi = int(q.get("oi") or oi)
                            iv = float(q.get("iv") or iv)
                except Exception:
                    pass

                delta = gamma = theta = vega = 0.0
                if use_api_greeks and strike:
                    try:
                        greeks = self.fetch_option_greeks(
                            symbol=symbol,
                            strike=strike,
                            expiry_date=expiry_date,
                            option_type=(opt_type.value if isinstance(opt_type, OptionType) else "CE"),
                            exchange="NFO",
                        )
                        if greeks:
                            delta = float(greeks.get("delta", 0.0))
                            gamma = float(greeks.get("gamma", 0.0))
                            theta = float(greeks.get("theta", 0.0))
                            vega = float(greeks.get("vega", 0.0))
                            iv = float(greeks.get("iv", iv))
                    except Exception:
                        pass

                return OptionContract(
                    symbol=symbol,
                    strike_price=strike,
                    expiry_date=expiry_date,
                    option_type=opt_type,
                    token=str(tsym),
                    timestamp=datetime.now(),
                    bid=bid,
                    ask=ask,
                    last_traded_price=ltp,
                    volume=int(volume),
                    open_interest=int(oi),
                    iv=float(iv),
                    delta=float(delta),
                    gamma=float(gamma),
                    theta=float(theta),
                    vega=float(vega),
                )

            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_build_contract, t) for t in tsym_list]
                contracts = [f.result() for f in futures if f]

            calls = [c for c in contracts if c.option_type == OptionType.CALL]
            puts = [c for c in contracts if c.option_type == OptionType.PUT]
            underlying = underlying_price or (contracts[0].strike_price if contracts else 0.0)
            return OptionChain(
                underlying_symbol=symbol,
                underlying_price=float(underlying),
                expiry_date=expiry_date,
                timestamp=datetime.now(),
                call_contracts=calls,
                put_contracts=puts,
            )
        except Exception:
            logger.exception("get_parsed_option_chain failed")
            return None
