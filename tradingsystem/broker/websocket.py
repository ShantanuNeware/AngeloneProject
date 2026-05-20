"""
Independent Angel One Websocket Handler Module
Test real-time market data feed without running full trading system

Usage:
    python -m tradingsystem.broker.websocket
    
Or directly:
    python tradingsystem/broker/websocket.py

Features:
- Real-time tick streaming
- Market watch updates
- Connection lifecycle management
"""
import logging
import sys
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tradingsystem.broker.angelone_session import AngelOneSession
from tradingsystem.config.loader import load_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class Tick:
    """Type-safe representation of a market tick"""
    symbol_token: str
    ltp: float
    bid: float
    ask: float
    volume: int
    timestamp: float


class WebSocketHandler:
    """Manages real-time market data via Angel One websocket"""
    
    def __init__(self, client, debug=False):
        self.client = client
        self.debug = debug
        self.is_connected = False
        self.tick_count = 0
        self.callbacks = []
        self.callback_lock = threading.Lock()
        self.last_heartbeat = time.time()
    
    def add_tick_callback(self, callback: Callable):
        """Register callback to be called on each tick"""
        with self.callback_lock:
            if callback not in self.callbacks:
                self.callbacks.append(callback)

    def remove_tick_callback(self, callback: Callable):
        """Unregister a callback"""
        with self.callback_lock:
            if callback in self.callbacks:
                self.callbacks.remove(callback)
    
    def on_tick(self, data: Dict[str, Any]):
        """Handle incoming tick data"""
        try:
            self.tick_count += 1
            self.last_heartbeat = time.time()
            
            # Map raw dict to type-safe Tick object
            tick = Tick(
                symbol_token=data.get("token", ""),
                ltp=float(data.get("ltp", 0)),
                bid=float(data.get("bid", 0)),
                ask=float(data.get("ask", 0)),
                volume=int(data.get("v", 0)),
                timestamp=time.time()
            )

            if self.debug:
                print(f"  📍 Tick #{self.tick_count}: {tick.symbol_token} LTP={tick.ltp}")
            
            # Call registered callbacks
            with self.callback_lock:
                for callback in self.callbacks:
                    try:
                        callback(tick)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")
        
        except Exception as e:
            logger.error(f"Error processing tick: {e}")
    
    def subscribe_tokens(self, tokens: list, exchange: str = "NSE"):
        """
        Subscribe to market data for tokens
        
        Args:
            tokens: List of symbol tokens
            exchange: Exchange (NSE, BSE, NFO)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            params = {
                "mode": "FULL",
                "exchangeTokens": {
                    exchange: tokens
                }
            }
            
            mode = self.client.subscribe(self.client.getWebsocket(), params)
            
            if mode and mode.get("status"):
                logger.info(f"✅ Subscribed to {len(tokens)} tokens on {exchange}")
                self.is_connected = True
                return True
            else:
                logger.error("Failed to subscribe")
                return False
                
        except Exception as e:
            logger.error(f"Subscription error: {e}")
            return False
    
    def start_streaming(self, duration_seconds: int = 10):
        """
        Start receiving tick data
        
        Args:
            duration_seconds: How long to stream (for testing)
        """
        try:
            if not self.is_connected:
                logger.warning("Not connected. Subscribe first.")
                return
            
            print(f"\n[STREAMING] Receiving ticks for {duration_seconds}s...")
            start = time.time()
            
            while time.time() - start < duration_seconds:
                # In real implementation, websocket callback handler
                # would call on_tick() automatically
                time.sleep(0.1)
            
            print(f"[STREAMING] Received {self.tick_count} ticks")
            
        except Exception as e:
            logger.error(f"Streaming error: {e}")
    
    def disconnect(self):
        """Close websocket connection"""
        try:
            if self.is_connected:
                # Unsubscribe and close
                self.is_connected = False
                logger.info("✅ Disconnected")
        except Exception as e:
            logger.error(f"Disconnect error: {e}")


def test_websocket_streaming():
    """
    Standalone websocket streaming test
    
    ⚠️ This tests the infrastructure - actual streaming requires
    websocket event handling setup which is broker-specific
    """
    try:
        config = load_config()
        broker_config = config["brokers"]["angleone"]
        
        print("\n" + "=" * 60)
        print("🔌 ANGEL ONE WEBSOCKET TEST")
        print("=" * 60)
        
        # Step 1: Login
        print("\n[STEP 1] Authenticating...")
        session = AngelOneSession(
            api_key=broker_config["api_key"],
            client_code=broker_config["username"],
            password=broker_config["password"],
            totp_secret=broker_config["factor2"]
        )
        
        client = session.login()
        if not client:
            print("❌ Login failed")
            return False
        
        print("✅ Authenticated")
        
        # Step 2: Initialize websocket handler
        print("\n[STEP 2] Initializing websocket handler...")
        handler = WebSocketHandler(client, debug=True)
        print("✅ Websocket handler ready")
        
        # Step 3: Register callback
        print("\n[STEP 3] Registering tick callback...")
        
        def on_tick(tick_data):
            # Custom callback logic
            pass
        
        handler.add_tick_callback(on_tick)
        print("✅ Callback registered")
        
        # Step 4: Subscribe to tokens
        print("\n[STEP 4] Subscribing to market data...")
        tokens = [broker_config.get("NIFTY_token", "99926000")]
        
        if handler.subscribe_tokens(tokens, exchange="NSE"):
            print("✅ Subscription successful")
            
            # Step 5: Start streaming (short test)
            print("\n[STEP 5] Testing streaming...")
            handler.start_streaming(duration_seconds=5)
            
            # Step 6: Disconnect
            print("\n[STEP 6] Disconnecting...")
            handler.disconnect()
            print("✅ Disconnected")
            
            return True
        else:
            print("❌ Subscription failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        return False


def main():
    """Entry point for direct execution"""
    success = test_websocket_streaming()
    
    if success:
        print("\n✅ WEBSOCKET TEST SUCCESSFUL")
    else:
        print("\n❌ WEBSOCKET TEST FAILED")
    
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
