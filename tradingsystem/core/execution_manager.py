"""
Execution Manager - Handles trade execution

Translates Strategy Signals into Broker Orders via OrderManager.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from tradingsystem.core.events import SyncEventBus, SignalGeneratedEvent
from tradingsystem.broker.order_manager import OrderManager
from tradingsystem.models.signal import SignalType
from tradingsystem.models.position import Position, PositionSide, PositionStatus

logger = logging.getLogger(__name__)

class ExecutionManager:
    """
    Orchestrates order placement based on strategy signals.
    Subscribes to SignalGeneratedEvent.
    """

    def __init__(self, event_bus: SyncEventBus, order_manager: OrderManager, config: dict):
        self.event_bus = event_bus
        self.order_manager = order_manager
        self.config = config
        self.active_positions: Dict[str, Position] = {}
        
        # Subscribe to signals
        self.event_bus.subscribe(SignalGeneratedEvent, self.handle_signal)
        logger.info("ExecutionManager initialized and subscribed to SignalGeneratedEvent")

    def handle_signal(self, event: SignalGeneratedEvent):
        """Process incoming signals and execute trades"""
        signal = event.signal
        
        if signal.signal_type == SignalType.HOLD:
            return

        logger.info(f"🚀 ExecutionManager processing signal: {signal.strategy_name} {signal.signal_type.value} {signal.symbol}")

        # Check if live execution is enabled in config
        if not self.config.get("system", {}).get("execute_signals", False):
            logger.info("⚠️ Execution skipped: 'execute_signals' is set to false in config.")
            return

        if signal.signal_type in [SignalType.BUY, SignalType.SELL]:
            self._execute_entry(signal)
        elif signal.signal_type == SignalType.EXIT:
            self._execute_exit(signal)

    def _execute_entry(self, signal):
        """Place an entry order"""
        # Determine order parameters from config/signal
        quantity = self.config.get("strategy", {}).get("quantity", 1)
        exchange = self.config.get("strategy", {}).get("exchange", "NSE")
        token = self.config.get("strategy", {}).get("token", "")
        
        # Transaction type mapping
        direction = "BUY" if signal.signal_type == SignalType.BUY else "SELL"
        
        # Handle Option specific logic if present in indicator_values
        if "strike" in signal.indicator_values:
            self._execute_option_order(signal, quantity, exchange)
            return

        # Standard Equity Order
        response = self.order_manager.place_order(
            symbol=signal.symbol,
            token=token,
            exchange=exchange,
            direction=direction,
            price=signal.price,
            quantity=quantity
        )

        if response and "orderid" in response:
            logger.info(f"✅ Entry order placed successfully. OrderID: {response['orderid']}")
            self._create_position_record(signal, response['orderid'], quantity)
        else:
            logger.error(f"❌ Entry order failed for {signal.symbol}")

    def _execute_option_order(self, signal, quantity, exchange):
        """Special handling for option multi-leg or single-leg orders"""
        strategy_type = signal.indicator_values.get("strategy")
        
        # For an Iron Condor, we would loop through legs here
        # For now, handle the primary strike identified in the signal
        strike = signal.indicator_values.get("strike")
        premium = signal.indicator_values.get("premium", signal.price)
        
        logger.info(f"📝 Executing Option {strategy_type} at strike {strike}")
        
        # In a real scenario, the token for the specific option contract 
        # would be resolved from the OptionChain before passing to the signal
        option_token = signal.indicator_values.get("token", "")
        
        self.order_manager.place_order(
            symbol=signal.symbol,
            token=option_token,
            exchange="NFO", # Options are usually on NFO
            direction="SELL", # Strategy is Option SELL
            price=premium,
            quantity=quantity,
            order_type="LIMIT"
        )

    def _execute_exit(self, signal):
        """Logic for closing existing positions"""
        logger.info(f"🏁 Executing exit for {signal.symbol}")
        # logic to find active position and reverse the transaction

    def _create_position_record(self, signal, order_id, quantity):
        """Track the newly opened position internally"""
        side = PositionSide.LONG if signal.signal_type == SignalType.BUY else PositionSide.SHORT
        
        new_pos = Position(
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            entry_price=signal.price,
            entry_time=datetime.now(),
            stop_loss=signal.indicator_values.get("stop_loss", 0),
            target=signal.indicator_values.get("target_price", 0),
            broker_order_id=order_id
        )
        self.active_positions[signal.symbol] = new_pos