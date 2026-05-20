"""Option Trading Models

Dataclasses for option chain data and option contracts.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from enum import Enum


class OptionType(Enum):
    """Option contract type"""
    CALL = "CE"
    PUT = "PE"


class OptionStrategy(Enum):
    """Option trading strategies"""
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    SHORT_CALL = "short_call"
    SHORT_PUT = "short_put"
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_CALL_SPREAD = "bear_call_spread"
    BULL_PUT_SPREAD = "bull_put_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    IRON_CONDOR = "iron_condor"
    STRADDLE = "straddle"
    STRANGLE = "strangle"


@dataclass
class OptionContract:
    """
    Single option contract (Call or Put at specific strike)
    """
    symbol: str                 # e.g., "NIFTY"
    strike_price: float         # e.g., 20000
    expiry_date: str            # e.g., "2026-05-30" (YYYY-MM-DD)
    option_type: OptionType     # CALL or PUT
    token: str                  # Unique broker identifier
    
    # Current market data
    timestamp: datetime         # Quote timestamp
    bid: float                  # Bid price (what buyers offer)
    ask: float                  # Ask price (what sellers ask)
    last_traded_price: float    # LTP (last traded price)
    volume: int                 # Trading volume
    open_interest: int          # Number of open contracts
    iv: float                   # Implied volatility (0.0-1.0)
    
    # Greeks (for risk management)
    delta: float = 0.0          # Price sensitivity (-1 to 1)
    gamma: float = 0.0          # Delta acceleration
    theta: float = 0.0          # Time decay per day
    vega: float = 0.0           # Volatility sensitivity
    rho: float = 0.0            # Interest rate sensitivity
    
    # Note: Validation removed - trust data source
    
    @property
    def mid_price(self) -> float:
        """Mid price between bid and ask"""
        return (self.bid + self.ask) / 2.0
    
    @property
    def bid_ask_spread(self) -> float:
        """Absolute spread between bid and ask"""
        return self.ask - self.bid
    
    @property
    def spread_percent(self) -> float:
        """Spread as percentage of mid price"""
        return (self.bid_ask_spread / self.mid_price * 100) if self.mid_price > 0 else 0.0
    
    @property
    def moneyness(self) -> str:
        """ATM, ITM, or OTM designation"""
        # This needs underlying price to determine accurately
        # Placeholder - will be set by option chain
        return "ATM"


@dataclass
class OptionChain:
    """
    Complete option chain for an underlying at a specific expiry
    """
    underlying_symbol: str      # e.g., "NIFTY"
    underlying_price: float     # Current underlying price
    expiry_date: str            # Contract expiry (YYYY-MM-DD)
    timestamp: datetime         # Quote timestamp
    
    call_contracts: List[OptionContract]   # All available calls
    put_contracts: List[OptionContract]    # All available puts
    
    # Volatility context (Step 5: IV rank tracking)
    iv_rank: float = 0.0                   # Current IV vs historical range (0-100)
    iv_percentile: float = 0.0             # % of time IV was lower than current (0-100)
    
    def __post_init__(self):
        """Validate option chain"""
        if not self.call_contracts and not self.put_contracts:
            raise ValueError("Option chain must have at least calls or puts")
        
        if self.underlying_price <= 0:
            raise ValueError("Underlying price must be positive")
    
    def get_atm_strike(self) -> float:
        """Get At-The-Money strike (closest to underlying price)"""
        all_strikes = set()
        for c in self.call_contracts:
            all_strikes.add(c.strike_price)
        for p in self.put_contracts:
            all_strikes.add(p.strike_price)
        
        return min(all_strikes, key=lambda x: abs(x - self.underlying_price))
    
    def get_call(self, strike: float) -> Optional[OptionContract]:
        """Get call contract at specific strike"""
        for contract in self.call_contracts:
            if contract.strike_price == strike:
                return contract
        return None
    
    def get_put(self, strike: float) -> Optional[OptionContract]:
        """Get put contract at specific strike"""
        for contract in self.put_contracts:
            if contract.strike_price == strike:
                return contract
        return None
    
    def get_atm_call(self) -> Optional[OptionContract]:
        """Get ATM call (closest to underlying price)"""
        atm_strike = self.get_atm_strike()
        return self.get_call(atm_strike)
    
    def get_atm_put(self) -> Optional[OptionContract]:
        """Get ATM put (closest to underlying price)"""
        atm_strike = self.get_atm_strike()
        return self.get_put(atm_strike)
    
    def get_otm_calls(self, num_strikes: int = 2) -> List[OptionContract]:
        """Get Out-of-The-Money calls (above underlying price)"""
        otm = [c for c in self.call_contracts if c.strike_price > self.underlying_price]
        otm.sort(key=lambda x: x.strike_price)
        return otm[:num_strikes]
    
    def get_otm_puts(self, num_strikes: int = 2) -> List[OptionContract]:
        """Get Out-of-The-Money puts (below underlying price)"""
        otm = [p for p in self.put_contracts if p.strike_price < self.underlying_price]
        otm.sort(key=lambda x: x.strike_price, reverse=True)
        return otm[:num_strikes]


@dataclass
class OptionPosition:
    """
    Open option position (single leg or multi-leg strategy)
    """
    position_id: str
    symbol: str
    strategy_type: OptionStrategy
    
    # Entry details
    entry_time: datetime
    entry_price: float          # Premium paid/received
    quantity: int               # Number of contracts
    
    # Position management
    current_price: float        # Current premium
    stop_loss_price: float      # SL premium level
    target_price: float         # TP premium level
    
    # Legs in multi-leg strategy
    long_contracts: List[OptionContract]    # Contracts we buy
    short_contracts: List[OptionContract]   # Contracts we sell
    
    # Status
    is_open: bool = True
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    pnl_percent: float = 0.0
    
    def __post_init__(self):
        """Validate option position"""
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive, got {self.quantity}")
    
    @property
    def net_delta(self) -> float:
        """Aggregate delta (Price sensitivity) of the entire position"""
        long_delta = sum(c.delta for c in self.long_contracts)
        short_delta = sum(c.delta for c in self.short_contracts)
        return (long_delta - short_delta) * self.quantity

    @property
    def net_theta(self) -> float:
        """Aggregate theta (Time decay) of the entire position"""
        long_theta = sum(c.theta for c in self.long_contracts)
        short_theta = sum(c.theta for c in self.short_contracts)
        return (long_theta - short_theta) * self.quantity

    @property
    def net_vega(self) -> float:
        """Aggregate vega (Volatility sensitivity) of the entire position"""
        long_vega = sum(c.vega for c in self.long_contracts)
        short_vega = sum(c.vega for c in self.short_contracts)
        return (long_vega - short_vega) * self.quantity

    @property
    def total_risk(self) -> float:
        """Maximum loss for this position"""
        if self.strategy_type in [OptionStrategy.LONG_CALL, OptionStrategy.LONG_PUT]:
            return self.entry_price * self.quantity
        elif self.strategy_type in [OptionStrategy.SHORT_CALL, OptionStrategy.SHORT_PUT]:
            return (abs(self.stop_loss_price - self.entry_price)) * self.quantity
        else:
            # Multi-leg spread has limited risk
            return abs(self.entry_price) * self.quantity
    
    @property
    def total_reward(self) -> float:
        """Maximum profit for this position"""
        if self.strategy_type in [OptionStrategy.LONG_CALL, OptionStrategy.LONG_PUT]:
            return (self.target_price - self.entry_price) * self.quantity
        elif self.strategy_type in [OptionStrategy.SHORT_CALL, OptionStrategy.SHORT_PUT]:
            return (self.entry_price - self.target_price) * self.quantity
        else:
            return abs(self.target_price - self.entry_price) * self.quantity
    
    @property
    def risk_reward_ratio(self) -> float:
        """Risk to reward ratio (should be > 1.0)"""
        if self.total_risk == 0:
            return 0.0
        return self.total_reward / self.total_risk
    
    def update_price(self, new_price: float) -> float:
        """Update position with new price, calculate P&L"""
        self.current_price = new_price
        
        # Calculate P&L based on position type
        if self.strategy_type in [OptionStrategy.LONG_CALL, OptionStrategy.LONG_PUT]:
            # Long position: profit when price goes up
            self.pnl = (new_price - self.entry_price) * self.quantity
        else:
            # Short position: profit when price goes down
            self.pnl = (self.entry_price - new_price) * self.quantity
        
        if self.entry_price != 0:
            self.pnl_percent = (self.pnl / (self.entry_price * self.quantity)) * 100
        
        return self.pnl
