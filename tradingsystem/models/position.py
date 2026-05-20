"""Position and Holdings Model"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PositionSide(Enum):
    """Position direction"""
    LONG = "long"
    SHORT = "short"


class PositionStatus(Enum):
    """Position lifecycle state"""
    OPEN = "open"
    CLOSED = "closed"
    PENDING = "pending"
    CANCELLED = "cancelled"


@dataclass
class Position:
    """
    Current open position in a symbol.
    
    Tracks entry, exit, P&L, and risk parameters.
    """
    
    symbol: str
    side: PositionSide  # LONG or SHORT
    quantity: int
    entry_price: float
    entry_time: datetime
    
    # Risk management
    stop_loss: float
    target: float
    
    # Current state
    current_price: Optional[float] = None
    current_time: Optional[datetime] = None
    status: PositionStatus = PositionStatus.OPEN
    
    # Exit details (when closed)
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    
    # Metadata
    strategy_name: str = ""
    signal_id: Optional[int] = None
    broker_order_id: Optional[str] = None
    notes: str = ""
    
    # Note: Validation removed - trust strategy code to create valid positions
    # Validate once at signal-to-position conversion, not on every instantiation
    
    @property
    def risk(self) -> float:
        """Risk per unit (entry to stop loss)"""
        return abs(self.entry_price - self.stop_loss)
    
    @property
    def reward(self) -> float:
        """Potential reward per unit (entry to target)"""
        return abs(self.target - self.entry_price)
    
    @property
    def risk_reward_ratio(self) -> float:
        """Risk/reward ratio (should be > 1.5)"""
        if self.risk == 0:
            return 0
        return self.reward / self.risk
    
    @property
    def notional_value(self) -> float:
        """Total position value at entry"""
        return self.quantity * self.entry_price
    
    @property
    def max_loss(self) -> float:
        """Maximum loss if stop loss hit"""
        return self.quantity * self.risk
    
    @property
    def max_profit(self) -> float:
        """Maximum profit if target hit"""
        return self.quantity * self.reward
    
    @property
    def unrealized_pnl(self) -> Optional[float]:
        """Unrealized P&L at current price"""
        if self.current_price is None or self.status != PositionStatus.OPEN:
            return None
        
        pnl_per_unit = self.current_price - self.entry_price
        if self.side == PositionSide.SHORT:
            pnl_per_unit = -pnl_per_unit
        
        return self.quantity * pnl_per_unit
    
    @property
    def unrealized_pnl_percent(self) -> Optional[float]:
        """Unrealized P&L as percentage"""
        if self.unrealized_pnl is None:
            return None
        
        return (self.unrealized_pnl / self.notional_value * 100)
    
    @property
    def realized_pnl(self) -> Optional[float]:
        """Realized P&L after exit"""
        if self.exit_price is None or self.status != PositionStatus.CLOSED:
            return None
        
        pnl_per_unit = self.exit_price - self.entry_price
        if self.side == PositionSide.SHORT:
            pnl_per_unit = -pnl_per_unit
        
        return self.quantity * pnl_per_unit
    
    def close(self, exit_price: float, exit_time: datetime) -> None:
        """Close the position"""
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.status = PositionStatus.CLOSED
    
    def hit_stop_loss(self) -> bool:
        """Check if current price hit stop loss"""
        if self.current_price is None:
            return False
        
        if self.side == PositionSide.LONG:
            return self.current_price <= self.stop_loss
        else:  # SHORT
            return self.current_price >= self.stop_loss
    
    def hit_target(self) -> bool:
        """Check if current price hit target"""
        if self.current_price is None:
            return False
        
        if self.side == PositionSide.LONG:
            return self.current_price >= self.target
        else:  # SHORT
            return self.current_price <= self.target
    
    def __str__(self) -> str:
        status = "OPEN" if self.status == PositionStatus.OPEN else "CLOSED"
        return (
            f"Position({status}: {self.side.value.upper()} {self.quantity} {self.symbol} "
            f"@ {self.entry_price:.2f}, R/R: {self.risk_reward_ratio:.2f})"
        )
