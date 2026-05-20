"""
Independent Angel One Order Manager Module
Test order placement and management without running full trading system

Usage:
    python -m tradingsystem.broker.order_manager
    
Or directly:
    python tradingsystem/broker/order_manager.py

⚠️ WARNING: This module actually places REAL orders. Use carefully!
"""
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tradingsystem.broker.angelone_session import AngelOneSession
from tradingsystem.config.loader import load_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OrderManager:
    """Manages order placement and tracking"""
    
    def __init__(self, client, dry_run: bool = False):
        self.client = client
        self.dry_run = bool(dry_run)
    
    def place_order(
        self,
        symbol: str,
        token: str,
        exchange: str,
        direction: str,
        price: float,
        quantity: int,
        order_type: str = "LIMIT",
        product_type: str = "MIS"
    ) -> Optional[Dict[str, Any]]:
        """
        Place an order on Angel One
        
        Args:
            symbol: Stock symbol (e.g., "NIFTY", "SBIN")
            token: Symbol token from broker
            exchange: Exchange (NSE, BSE, NFO)
            direction: BUY or SELL
            price: Order price
            quantity: Order quantity
            order_type: LIMIT, MARKET, STOP-LOSS, STOP-LIMIT
            product_type: MIS (intraday), CNC (delivery)
        
        Returns:
            Order response dict or None if failed
        """
        try:
            # Dry-run simulation: don't call broker API
            if getattr(self, 'dry_run', False):
                fake_id = f"DRY-{int(time.time())}"
                logger.info(f"[DRY-RUN] Simulated order: {symbol} {direction} {quantity}@{price} (id={fake_id})")
                return {"orderid": fake_id}
            params = {
                "mode": "FULL",
                "exchangeTokens": {
                    exchange: [token]
                }
            }
            
            # Fetch LTP (last traded price)
            ltp_data = self.client.getMarketData(params)
            if not ltp_data or not ltp_data.get("status"):
                logger.error(f"Could not fetch LTP for {symbol}")
                return None
            
            # Place order
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": token,
                "transactiontype": direction,
                "exchange": exchange,
                "ordertype": order_type,
                "producttype": product_type,
                "price": price,
                "quantity": quantity
            }
            
            response = self.client.placeOrder(order_params)
            
            if response and response.get("status"):
                logger.info(f"✅ Order placed: {symbol} {direction} {quantity}@{price}")
                return response.get("data", {})
            else:
                logger.error(f"❌ Order failed: {response}")
                return None
                
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    def get_orders(self) -> Optional[list]:
        """Fetch all orders for today"""
        try:
            if getattr(self, 'dry_run', False):
                logger.info("[DRY-RUN] get_orders called — returning empty list")
                return []

            response = self.client.orderBook()
            if response and response.get("status"):
                return response.get("data", [])
            return None
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order"""
        try:
            if getattr(self, 'dry_run', False):
                logger.info(f"[DRY-RUN] cancel_order called for {order_id} — simulated success")
                return True

            params = {
                "variety": "NORMAL",
                "orderid": order_id
            }
            response = self.client.cancelOrder(params)
            if response and response.get("status"):
                logger.info(f"✅ Order cancelled: {order_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False


def test_order_management():
    """
    Standalone order management test
    
    ⚠️ This does NOT place real orders - it only tests the workflow
    To place real orders, uncomment place_order() call
    """
    try:
        config = load_config()
        broker_config = config["brokers"]["angleone"]
        
        print("\n" + "=" * 60)
        print("📋 ANGEL ONE ORDER MANAGER TEST")
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
        
        # Step 2: Initialize order manager
        print("\n[STEP 2] Initializing order manager...")
        manager = OrderManager(client)
        print("✅ Order manager ready")
        
        # Step 3: Fetch existing orders
        print("\n[STEP 3] Fetching order book...")
        orders = manager.get_orders()
        
        if orders is None:
            print("❌ Could not fetch orders")
            return False
        
        print(f"✅ Total orders today: {len(orders)}")
        
        if orders:
            print("\n   Sample orders (last 3):")
            print("   Symbol | Direction | Quantity | Price | Status")
            print("   " + "-" * 50)
            for order in orders[-3:]:
                symbol = order.get("tradingsymbol", "N/A")
                direction = order.get("transactiontype", "N/A")
                qty = order.get("quantity", "N/A")
                price = order.get("price", "N/A")
                status = order.get("status", "N/A")
                print(f"   {symbol} | {direction} | {qty} | {price} | {status}")
        
        print("\n⚠️ ORDER PLACEMENT SKIPPED (test only)")
        print("   To place real orders, modify this script")
        
        return True
            
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        return False


def main():
    """Entry point for direct execution"""
    success = test_order_management()
    
    if success:
        print("\n✅ ORDER MANAGER TEST SUCCESSFUL")
    else:
        print("\n❌ ORDER MANAGER TEST FAILED")
    
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
