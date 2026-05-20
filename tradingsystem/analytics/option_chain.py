from typing import List, Dict, Any
import statistics

from tradingsystem.models.option import OptionChain, OptionContract


def detect_gamma_burst(option_chain: OptionChain, zscore_threshold: float = 2.0) -> List[Dict[str, Any]]:
    """Detect strikes with unusually high gamma exposure.

    Returns list of dicts: {strike, gamma_exposure}
    """
    exposures = {}
    for c in option_chain.call_contracts + option_chain.put_contracts:
        key = c.strike_price
        exposures.setdefault(key, 0.0)
        exposures[key] += abs(getattr(c, "gamma", 0.0)) * (getattr(c, "open_interest", 0) or 0)

    if not exposures:
        return []

    vals = list(exposures.values())
    mean = statistics.mean(vals)
    stdev = statistics.pstdev(vals) if len(vals) > 1 else 0.0

    bursts = []
    for strike, val in exposures.items():
        z = (val - mean) / stdev if stdev > 0 else 0.0
        if z >= zscore_threshold:
            bursts.append({"strike": strike, "gamma_exposure": val, "zscore": z})
    bursts.sort(key=lambda x: x["gamma_exposure"], reverse=True)
    return bursts


def detect_liquidity_pools(option_chain: OptionChain, oi_factor: float = 3.0, min_oi: int = 1000) -> List[Dict[str, Any]]:
    """Identify strikes with large open interest compared to typical strikes."""
    oi_by_strike = {}
    for c in option_chain.call_contracts + option_chain.put_contracts:
        oi_by_strike.setdefault(c.strike_price, 0)
        oi_by_strike[c.strike_price] += getattr(c, "open_interest", 0) or 0

    if not oi_by_strike:
        return []

    vals = list(oi_by_strike.values())
    median = statistics.median(vals)

    pools = []
    for strike, oi in oi_by_strike.items():
        if oi >= max(min_oi, median * oi_factor):
            pools.append({"strike": strike, "oi": oi})
    pools.sort(key=lambda x: x["oi"], reverse=True)
    return pools


def select_best_option(option_chain: OptionChain, side: str = "call", num_candidates: int = 3) -> List[OptionContract]:
    """Rank and return top option contracts for the requested side.

    Scoring heuristic: prefer low spread, reasonable IV, high OI, and delta depending on side.
    """
    candidates: List[OptionContract] = []
    if side.lower() in ("call", "c"):
        candidates = option_chain.call_contracts
    else:
        candidates = option_chain.put_contracts

    def score(c: OptionContract) -> float:
        spread = c.bid_ask_spread if c.bid_ask_spread is not None else 1.0
        iv = c.iv if c.iv is not None else 0.0
        oi = getattr(c, "open_interest", 0) or 0
        delta = abs(getattr(c, "delta", 0.0))

        # lower spread better, higher oi better, iv moderate preferred
        s = 0.0
        s += (oi / 1000.0)
        s += max(0.0, 1.0 - (spread / (c.mid_price + 1e-6))) * 2.0
        s += max(0.0, 1.0 - abs(iv - 0.2))  # prefer iv near 20%
        s += (1.0 - abs(delta - 0.3))  # prefer delta ~0.3
        return s

    scored = [(score(c), c) for c in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:num_candidates]]
