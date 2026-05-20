"""Trade Execution and Setup Models"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TradeSetup:
    """
    Risk-reward validated trade setup.
    
    Every trade must have proper risk/reward defined before entry.
    Ensures minimum risk/reward ratio (typically > 1.5) for viability.
    """
    
    symbol: str
    entry: float
    stop_loss: float
    target: float
    
    # Quantity calculated from risk
    quantity: Optional[int] = None
    
    # Metadata
    strategy: str = ""
    regime: str = ""
    confidence: float = 0.5  # 0.0 to 1.0
    
    def __post_init__(self):
        """Validate setup parameters"""
        if self.entry <= 0:
            raise ValueError(f"Entry must be positive, got {self.entry}")
        
        if self.stop_loss <= 0:
            raise ValueError(f"Stop loss must be positive, got {self.stop_loss}")
        
        if self.target <= 0:
            raise ValueError(f"Target must be positive, got {self.target}")
        
        # Determine direction based on prices
        self.is_long = self.target > self.entry
        
        # Validate setup based on direction
        if self.is_long:
            if not (self.stop_loss < self.entry < self.target):
                raise ValueError(
                    f"LONG setup invalid: {self.stop_loss} < {self.entry} < {self.target}"
                )
        else:
            if not (self.target < self.entry < self.stop_loss):
                raise ValueError(
                    f"SHORT setup invalid: {self.target} < {self.entry} < {self.stop_loss}"
                )
    
    @property
    def direction(self) -> str:
        """BUY or SELL"""
        return "BUY" if self.is_long else "SELL"
    
    @property
    def risk(self) -> float:
        """Risk per unit (entry to stop loss)"""
        return abs(self.entry - self.stop_loss)
    
    @property
    def reward(self) -> float:
        """Reward per unit (entry to target)"""
        return abs(self.target - self.entry)
    
    @property
    def risk_reward_ratio(self) -> float:
        """Risk/reward ratio (minimum: 1.5)"""
        if self.risk == 0:
            return 0
        return self.reward / self.risk
    
    @property
    def is_valid(self) -> bool:
        """Setup meets minimum risk/reward (> 1.5)"""
        return self.risk_reward_ratio > 1.5
    
    def calculate_position_size(
        self,
        account_balance: float,
        risk_percent: float = 1.0  # Risk 1% of account per trade
    ) -> int:
        """
        Calculate position size based on account balance and risk tolerance.
        
        Formula:
            risk_amount = account_balance * risk_percent
            position_size = risk_amount / risk_per_unit
        """
        if account_balance <= 0:
            raise ValueError(f"Account balance must be positive, got {account_balance}")
        
        if not 0 < risk_percent <= 10:
            raise ValueError(f"Risk percent must be 0-10%, got {risk_percent}")
        
        risk_amount = account_balance * (risk_percent / 100.0)
        position_size = int(risk_amount / self.risk)
        
        return max(position_size, 1)  # Minimum 1 unit
    
    def __str__(self) -> str:
        return (
            f"TradeSetup({self.direction} {self.symbol} @ {self.entry:.2f}, "
            f"SL: {self.stop_loss:.2f}, TP: {self.target:.2f}, "
            f"R/R: {self.risk_reward_ratio:.2f})"
        )


@dataclass
class Trade:
    """
    Executed trade with entry and exit.
    
    Tracks complete trade lifecycle and performance.
    """
    
    id: str  # Unique trade ID
    symbol: str
    entry_time: datetime
    entry_price: float
    stop_loss: float
    target: float
    quantity: int
    
    strategy: str = ""
    signal_id: Optional[int] = None
    
    # Exit details
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""  # "target", "stoploss", "manual", "timeout"
    
    @property
    def is_long(self) -> bool:
        """True if long trade"""
        return self.target > self.entry_price
    
    @property
    def is_short(self) -> bool:
        """True if short trade"""
        return self.target < self.entry_price
    
    @property
    def is_open(self) -> bool:
        """Trade not yet closed"""
        return self.exit_price is None
    
    @property
    def is_closed(self) -> bool:
        """Trade completed"""
        return self.exit_price is not None
    
    @property
    def risk(self) -> float:
        """Risk per unit"""
        return abs(self.entry_price - self.stop_loss)
    
    @property
    def reward(self) -> float:
        """Potential reward per unit"""
        return abs(self.target - self.entry_price)
    
    @property
    def risk_reward_ratio(self) -> float:
        """Risk/reward ratio"""
        if self.risk == 0:
            return 0
        return self.reward / self.risk
    
    @property
    def realized_pnl(self) -> Optional[float]:
        """Profit/loss on completed trade"""
        if not self.is_closed or self.exit_price is None:
            return None
        
        pnl_per_unit = self.exit_price - self.entry_price
        if self.is_short:
            pnl_per_unit = -pnl_per_unit
        
        return self.quantity * pnl_per_unit
    
    @property
    def realized_pnl_percent(self) -> Optional[float]:
        """P&L as percentage of entry"""
        if self.realized_pnl is None:
            return None
        
        entry_value = self.quantity * self.entry_price
        return (self.realized_pnl / entry_value * 100)
    
    @property
    def duration(self) -> Optional[float]:
        """Trade duration in seconds"""
        if not self.is_closed or self.exit_time is None:
            return None
        
        return (self.exit_time - self.entry_time).total_seconds()
    
    @property
    def was_profitable(self) -> Optional[bool]:
        """True if trade made money"""
        if self.realized_pnl is None:
            return None
        
        return self.realized_pnl > 0
    
    @property
    def hit_target(self) -> Optional[bool]:
        """True if exited at target"""
        if not self.is_closed or self.exit_price is None:
            return None
        
        if self.is_long:
            return abs(self.exit_price - self.target) < 0.01
        else:
            return abs(self.exit_price - self.target) < 0.01
    
    @property
    def hit_stoploss(self) -> Optional[bool]:
        """True if exited at stop loss"""
        if not self.is_closed or self.exit_price is None:
            return None
        
        if self.is_long:
            return abs(self.exit_price - self.stop_loss) < 0.01
        else:
            return abs(self.exit_price - self.stop_loss) < 0.01
    
    def close(self, exit_price: float, exit_time: datetime, reason: str = "manual") -> None:
        """Close the trade"""
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason
    
    def __str__(self) -> str:
        direction = "LONG" if self.is_long else "SHORT"
        status = "OPEN" if self.is_open else f"CLOSED @ {self.exit_price:.2f}"
        return (
            f"Trade({direction} {self.quantity} {self.symbol} @ {self.entry_price:.2f}, "
            f"{status}, R/R: {self.risk_reward_ratio:.2f})"
        )
