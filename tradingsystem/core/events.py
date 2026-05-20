"""
Simplified Event System - Minimal necessary events only

Removed complexity:
- Removed 12+ unused event types (OrderSubmittedEvent, PositionOpenedEvent, etc.)
- Removed async EventBus (using SyncEventBus only)
- Removed EventHandler abstract class
- Removed event history tracking (not needed for live trading)
- Removed complex inheritance and type checking

Kept:
- SignalGeneratedEvent (used by strategies)
- CandleClosedEvent (used for market data)
- Simple SyncEventBus (publish/subscribe pattern)
"""

from typing import Optional, Any, Dict, List, Callable
from dataclasses import dataclass
from datetime import datetime
from tradingsystem.models.signal import Signal


# ============================================================================
# ESSENTIAL EVENTS ONLY
# ============================================================================

@dataclass
class CandleClosedEvent:
    """Market data: when a candle closes"""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    timeframe: str


@dataclass
class SignalGeneratedEvent:
    """Strategy output: trading signal"""
    signal: Signal


# ============================================================================
# SIMPLE SYNC EVENT BUS
# ============================================================================

class SyncEventBus:
    """
    Simple synchronous event bus.
    
    No async, no history tracking, no complex patterns.
    Just publish -> handler(event).
    """
    
    def __init__(self):
        # {EventType: [handler1, handler2, ...]}
        self._handlers: Dict[type, List[Callable]] = {}
    
    def subscribe(self, event_type: type, handler: Callable) -> None:
        """Register handler for event type"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    def publish(self, event: Any) -> None:
        """Publish event to all subscribers of that type"""
        event_type = type(event)
        if event_type in self._handlers:
            for handler in self._handlers[event_type]:
                handler(event)


# ============================================================================
# EXAMPLE USAGE (if run directly)
# ============================================================================

if __name__ == "__main__":
    bus = SyncEventBus()
    
    def on_signal(event: SignalGeneratedEvent):
        print(f"SIGNAL: {event.strategy_name} - {event.signal_type.upper()} {event.symbol}")
    
    bus.subscribe(SignalGeneratedEvent, on_signal)
    
    from tradingsystem.models.signal import Signal, SignalType
    
    test_signal = Signal(
        strategy_name="MA",
        symbol="NIFTY",
        signal_type=SignalType.BUY,
        timestamp=datetime.now(),
        price=20000.0,
        confidence=0.85,
        regime="TRENDING",
        reason="Golden cross",
        indicator_values={"ma_fast": 20050, "ma_slow": 19950}
    )
    
    bus.publish(SignalGeneratedEvent(signal=test_signal))
