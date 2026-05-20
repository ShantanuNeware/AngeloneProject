"""Core Module - Event-Driven Trading Engine Core"""

# Import in order to avoid circular dependencies
# Events first (no dependencies on other core modules)
from .events import SyncEventBus, SignalGeneratedEvent

# Regime manager (depends only on events, not on strategies)
from .regime_manager import RegimeManager, RegimeAwareFilter

# Strategy manager last (depends on BaseStrategy which imports events)
from .strategy_manager import StrategyManager, StrategyManagerConfig

# Execution manager (depends on events and order manager)
from .execution_manager import ExecutionManager

__all__ = [
    "SyncEventBus",
    "SignalGeneratedEvent",
    "RegimeManager",
    "RegimeAwareFilter",
    "StrategyManager",
    "StrategyManagerConfig",
    "ExecutionManager",
]
